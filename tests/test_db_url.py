import pytest

from core.db_url import parse_database_url

NEON = (
    "postgresql://neondb_owner:secret@ep-rapid-flower-abc123-pooler.c-8.us-east-2.aws.neon.tech"
    "/neondb?sslmode=require&channel_binding=require"
)


def test_neon_pooler_url_is_translated():
    cfg = parse_database_url(NEON)
    assert cfg.is_postgres and cfg.uses_pooler
    assert cfg.url.drivername == "postgresql+asyncpg"
    assert cfg.url.query == {}  # libpq-only parameters removed
    assert cfg.url.database == "neondb" and cfg.url.username == "neondb_owner"
    assert cfg.connect_args["ssl"] == "require"
    assert cfg.connect_args["statement_cache_size"] == 0
    assert cfg.connect_args["prepared_statement_cache_size"] == 0
    assert cfg.connect_args["prepared_statement_name_func"]() != cfg.connect_args["prepared_statement_name_func"]()


def test_direct_neon_url_keeps_statement_cache():
    cfg = parse_database_url(NEON.replace("-pooler", ""))
    assert not cfg.uses_pooler
    assert "statement_cache_size" not in cfg.connect_args
    assert cfg.connect_args["ssl"] == "require"


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg2", "postgresql+asyncpg"])
def test_postgres_schemes_become_asyncpg(scheme):
    cfg = parse_database_url(f"{scheme}://u:p@db.example.com/app")
    assert cfg.url.drivername == "postgresql+asyncpg"
    assert cfg.connect_args["ssl"] == "require"  # remote host: TLS by default


def test_localhost_without_sslmode_has_no_tls():
    assert "ssl" not in parse_database_url("postgresql://u:p@localhost:5432/app").connect_args


def test_sslmode_disable_has_no_tls():
    assert "ssl" not in parse_database_url("postgresql://u:p@db.example.com/app?sslmode=disable").connect_args


def test_sqlite_url_gets_async_driver():
    cfg = parse_database_url("sqlite:///./constructor.db")
    assert cfg.is_sqlite and cfg.url.drivername == "sqlite+aiosqlite"


def test_unsupported_backend_rejected():
    with pytest.raises(ValueError):
        parse_database_url("mysql://u:p@host/db")


def test_password_is_not_in_error_message():
    with pytest.raises(ValueError) as exc:
        parse_database_url("mysql://u:topsecret@host/db")
    assert "topsecret" not in str(exc.value)
