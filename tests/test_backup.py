import datetime as dt
import gzip
import os
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from core import backup
from core.config import settings

TZ = ZoneInfo("Asia/Tashkent")


def at(h, m=0, day=14):
    return dt.datetime(2026, 11, day, h, m, tzinfo=TZ)


def test_literal_rendering():
    assert backup.literal(None) == "NULL"
    assert backup.literal(True) == "TRUE" and backup.literal(False) == "FALSE"
    assert backup.literal(5) == "5"
    assert backup.literal("O'Brien") == "'O''Brien'"
    assert backup.literal("a\\b") == "'a\\b'"
    assert backup.literal({"k": "é"}) == "'{\"k\": \"é\"}'"
    assert backup.literal(b"\x01\xff") == "'\\x01ff'"
    assert backup.literal(dt.datetime(2026, 1, 2, 3, 4)) == "'2026-01-02T03:04:00'"


def test_is_due_window_and_once_per_day():
    assert not backup.is_due(at(19, 59), None, 20)
    assert backup.is_due(at(20, 0), None, 20)
    assert backup.is_due(at(20, 29), None, 20)
    assert not backup.is_due(at(20, 30), None, 20)
    assert not backup.is_due(at(20, 5), dt.date(2026, 11, 14), 20)
    assert backup.is_due(at(20, 5, day=15), dt.date(2026, 11, 14), 20)


def test_split_file(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"x" * 25)
    assert backup.split_file(str(path), 100) == [str(path)]
    parts = backup.split_file(str(path), 10)
    assert [os.path.getsize(p) for p in parts] == [10, 10, 5]
    assert b"".join(open(p, "rb").read() for p in parts) == b"x" * 25


async def test_dump_contains_schema_rows_and_version(env, tmp_path):
    path = str(tmp_path / "b.sql.gz")
    info = await backup.make_dump(env.engine, path)
    sql = gzip.open(path, "rt", encoding="utf-8").read()
    assert info["tables"] > 10 and info["rows"] >= 1
    assert 'CREATE TABLE bots' in sql or 'CREATE TABLE "bots"' in sql
    assert 'INSERT INTO "bots"' in sql
    assert 'INSERT INTO "alembic_version"' in sql
    assert "setval(" in sql


class Sender:
    def __init__(self, fail=()):
        self.docs, self.msgs, self.fail = [], [], set(fail)

    async def send_document(self, chat_id, document, filename=None, caption=None, parse_mode=None):
        if chat_id in self.fail:
            raise RuntimeError("blocked")
        self.docs.append((chat_id, filename, len(document.read()), caption))

    async def send_message(self, chat_id, text, **kw):
        self.msgs.append((chat_id, text))


async def test_send_backup_to_every_admin_skips_unreachable(env):
    bot = Sender(fail={2})
    sent = await backup.send_backup(bot, [1, 2, 3], env.engine, now=at(20))
    assert sent == 2
    assert [d[0] for d in bot.docs] == [1, 3]
    chat, name, size, caption = bot.docs[0]
    assert name == "telecraft_backup_2026-11-14_2000.sql.gz" and size > 100
    assert "Baza zaxira nusxasi" in caption


async def test_loop_sends_once_a_day_and_reports_failure(env, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_IDS", "1")
    bot = Sender()
    times = iter([at(19, 0), at(20, 0), at(20, 1), at(20, 2)])
    calls = []

    async def stop_sleep(_):
        if len(calls) >= 4:
            raise KeyboardInterrupt
        calls.append(1)

    with pytest.raises(KeyboardInterrupt):
        await backup.backup_loop(lambda: bot, env.engine, sleep=stop_sleep, clock=lambda: next(times))
    assert len(bot.docs) == 1  # at 20:00 only; 20:01 and 20:02 are the same day

    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(backup, "send_backup", boom)
    bot2 = Sender()
    times = iter([at(20, 0, day=16)])
    calls.clear()
    calls.extend([1, 1, 1, 1])
    with pytest.raises(KeyboardInterrupt):
        await backup.backup_loop(lambda: bot2, env.engine, sleep=stop_sleep, clock=lambda: next(times))
    assert bot2.msgs and "yaratilmadi" in bot2.msgs[0][1]
