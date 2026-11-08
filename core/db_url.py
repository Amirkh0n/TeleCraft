"""Turn a user-supplied DATABASE_URL into SQLAlchemy async settings.

Hosting providers (Neon, Supabase, Render...) hand out libpq-style URLs such as
``postgresql://user:pass@host/db?sslmode=require&channel_binding=require``.
SQLAlchemy's asyncpg driver needs a different driver name and does not understand
the libpq query parameters, so they are translated here. The URL (it contains a
password) is never logged.
"""
import uuid
from dataclasses import dataclass, field

from sqlalchemy.engine import URL, make_url

# libpq parameters asyncpg cannot take as URL query arguments.
_LIBPQ_ONLY = {"sslmode", "channel_binding", "sslrootcert", "sslcert", "sslkey", "options"}
_SSL_ON = {"require", "verify-ca", "verify-full", "prefer", "allow"}


@dataclass
class DatabaseConfig:
    url: URL
    connect_args: dict = field(default_factory=dict)
    is_sqlite: bool = False
    is_postgres: bool = False
    uses_pooler: bool = False


def parse_database_url(raw: str) -> DatabaseConfig:
    url = make_url(raw.strip())
    backend = url.get_backend_name()

    if backend == "sqlite":
        return DatabaseConfig(url.set(drivername="sqlite+aiosqlite"), is_sqlite=True)

    if backend not in ("postgresql", "postgres"):
        raise ValueError(f"Unsupported DATABASE_URL backend: {backend}")

    query = dict(url.query)
    sslmode = str(query.pop("sslmode", "")).lower()
    for key in list(query):
        if key in _LIBPQ_ONLY:
            query.pop(key)

    connect_args: dict = {}
    if sslmode in _SSL_ON:
        connect_args["ssl"] = "require" if sslmode in ("require", "prefer", "allow") else sslmode
    elif sslmode == "":
        # Managed hosts always need TLS; plain localhost does not.
        host = url.host or ""
        if host and host not in ("localhost", "127.0.0.1", "::1"):
            connect_args["ssl"] = "require"

    # Neon/pgBouncer "pooler" hosts run in transaction mode: no prepared statements.
    uses_pooler = "-pooler" in (url.host or "") or "pooler." in (url.host or "")
    if uses_pooler:
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid.uuid4()}__"

    url = url.set(drivername="postgresql+asyncpg", query=query)
    return DatabaseConfig(url, connect_args, is_postgres=True, uses_pooler=uses_pooler)
