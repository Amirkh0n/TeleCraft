"""Daily database backup: a gzip-compressed SQL file sent to the main bot's admins.

The dump is produced in pure Python (no ``pg_dump`` needed, so it works on any host). It holds the
schema (``CREATE TABLE``/indexes), every row as ``INSERT`` and the sequence positions, so it can be
loaded into an *empty* PostgreSQL database with ``gunzip -c file.sql.gz | psql "$DATABASE_URL"``.
Bot tokens are stored encrypted: keep ``ENCRYPTION_KEY`` safe, the backup is useless without it.
"""
import asyncio
import datetime as dt
import decimal
import gzip
import json
import os
import tempfile
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy import Enum
from sqlalchemy.schema import CreateIndex, CreateTable

from core.config import settings
from core.logger import get_logger

logger = get_logger("backup")

BATCH_ROWS = 200
TELEGRAM_LIMIT = 49 * 1024 * 1024  # Telegram bots may upload files up to 50 MB
WINDOW_MINUTES = 30  # a restart this late after BACKUP_HOUR still sends today's backup
CHECK_INTERVAL = 60


def literal(value) -> str:
    """One Python value as a PostgreSQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, decimal.Decimal)):
        return str(value)
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    elif isinstance(value, (dt.datetime, dt.date, dt.time)):
        value = value.isoformat()
    elif isinstance(value, uuid.UUID):
        value = str(value)
    elif isinstance(value, (bytes, bytearray, memoryview)):
        return "'\\x" + bytes(value).hex() + "'"
    return "'" + str(value).replace("'", "''").replace("\x00", "") + "'"


def _ddl(table) -> list[str]:
    dialect = postgresql.dialect()
    out = [str(CreateTable(table).compile(dialect=dialect)).strip() + ";"]
    out += [str(CreateIndex(index).compile(dialect=dialect)).strip() + ";" for index in table.indexes]
    return out


def _enum_types(tables) -> list[str]:
    """``CREATE TYPE`` for every native enum column (PostgreSQL needs them before the tables)."""
    seen, out = set(), []
    for table in tables:
        for column in table.columns:
            kind = column.type
            if isinstance(kind, Enum) and kind.native_enum and kind.name and kind.name not in seen:
                seen.add(kind.name)
                labels = ", ".join(literal(v) for v in kind.enums)
                out.append(f'CREATE TYPE "{kind.name}" AS ENUM ({labels});')
    return out


def _has_serial_id(table) -> bool:
    pk = list(table.primary_key.columns)
    return len(pk) == 1 and pk[0].name == "id" and pk[0].type.python_type is int


async def _write_table(conn, table, out) -> int:
    columns = [c.name for c in table.columns]
    head = f'INSERT INTO "{table.name}" (' + ", ".join(f'"{c}"' for c in columns) + ") VALUES\n"
    batch: list[str] = []
    total = 0

    def flush():
        if batch:
            out.write(head + ",\n".join(batch) + ";\n")
            batch.clear()

    result = await conn.stream(select(table))
    async for row in result:
        batch.append("(" + ", ".join(literal(v) for v in row) + ")")
        total += 1
        if len(batch) >= BATCH_ROWS:
            flush()
    flush()
    if total and _has_serial_id(table):
        out.write(f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', 'id'), "
                  f'(SELECT MAX("id") FROM "{table.name}"));\n')
    return total


async def make_dump(engine, path: str) -> dict:
    """Write the gzip SQL dump to ``path``. Returns ``{"tables": n, "rows": n}``."""
    import models  # noqa: F401  (registers every table)
    from models.base import Base

    rows = 0
    tables = list(Base.metadata.sorted_tables)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    async with engine.connect() as conn:
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as out:
            out.write(f"-- TeleCraft database backup, {stamp}\n-- Load into an EMPTY PostgreSQL database.\n")
            out.write("SET client_encoding = 'UTF8';\nSET standard_conforming_strings = on;\n\n")
            for statement in _enum_types(tables):
                out.write(statement + "\n")
            for table in tables:
                out.write("\n".join(_ddl(table)) + "\n")
            try:
                version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            except Exception:
                version = None
                await conn.rollback()
            if version:
                out.write('CREATE TABLE "alembic_version" ("version_num" VARCHAR(32) NOT NULL PRIMARY KEY);\n')
                out.write(f'INSERT INTO "alembic_version" VALUES ({literal(version)});\n')
            out.write("\nSET session_replication_role = replica;\n")  # insert order no longer matters
            for table in tables:
                rows += await _write_table(conn, table, out)
            out.write("SET session_replication_role = DEFAULT;\n")
    return {"tables": len(tables), "rows": rows}


def split_file(path: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Cut a too-big file into ``path.part001``... (joined again with ``cat``)."""
    if os.path.getsize(path) <= limit:
        return [path]
    parts = []
    with open(path, "rb") as src:
        while chunk := src.read(limit):
            part = f"{path}.part{len(parts) + 1:03d}"
            with open(part, "wb") as dst:
                dst.write(chunk)
            parts.append(part)
    return parts


def _size(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{max(1, n // 1024)} KB"


async def send_backup(bot, admin_ids, engine, *, now=None) -> int:
    """Dump the database and send it to every admin. Returns how many admins received it."""
    stamp = (now or dt.datetime.now(ZoneInfo(settings.BACKUP_TIMEZONE))).strftime("%Y-%m-%d_%H%M")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, f"telecraft_backup_{stamp}.sql.gz")
        info = await make_dump(engine, path)
        parts = split_file(path)
        caption = (f"🗄 Baza zaxira nusxasi\n📅 {stamp.replace('_', ' ')}\n"
                   f"📊 {info['tables']} jadval, {info['rows']} qator, {_size(os.path.getsize(path))}")
        if len(parts) > 1:
            caption += f"\n⚠️ Fayl {len(parts)} bo'lakka bo'lindi: <code>cat *.part* > backup.sql.gz</code>"
        sent = 0
        for admin in admin_ids:
            try:
                for number, part in enumerate(parts, 1):
                    with open(part, "rb") as fh:
                        await bot.send_document(chat_id=admin, document=fh, filename=os.path.basename(part),
                                                caption=caption if number == 1 else None, parse_mode="HTML")
                sent += 1
            except Exception as exc:  # the admin never started the main bot, or blocked it
                logger.warning("Backup not delivered to admin %s: %s", admin, exc)
    return sent


async def _notify_failure(bot, admin_ids, error) -> None:
    for admin in admin_ids:
        try:
            await bot.send_message(chat_id=admin, text=f"⚠️ Kunlik zaxira nusxa yaratilmadi:\n{error}"[:3500])
        except Exception:
            pass


def is_due(now: dt.datetime, last_sent: dt.date | None, hour: int) -> bool:
    """True from ``hour``:00 for WINDOW_MINUTES, once per local day."""
    start = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return last_sent != now.date() and start <= now < start + dt.timedelta(minutes=WINDOW_MINUTES)


async def backup_loop(get_bot, engine, *, sleep=asyncio.sleep, clock=None) -> None:
    """Once a day at BACKUP_HOUR sends the backup to ``settings.admin_ids_list``."""
    last_sent = None
    tz = ZoneInfo(settings.BACKUP_TIMEZONE)
    while True:
        try:
            now = clock() if clock else dt.datetime.now(tz)
            admins = settings.admin_ids_list
            bot = get_bot()
            if bot and admins and is_due(now, last_sent, settings.BACKUP_HOUR):
                last_sent = now.date()
                try:
                    sent = await send_backup(bot, admins, engine, now=now)
                    logger.info("Daily backup sent to %s admin(s)", sent)
                except Exception as exc:
                    logger.exception("Daily backup failed")
                    await _notify_failure(bot, admins, exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("backup loop error")
        await sleep(CHECK_INTERVAL)
