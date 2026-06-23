"""SQLite database setup using SQLAlchemy (MVP persistence layer)."""
from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ..settings import get_settings

settings = get_settings()

# check_same_thread=False so FastAPI's threadpool can share the SQLite engine.
_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create tables. Imported lazily so models register on the metadata."""
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()


def _migrate_sqlite() -> None:
    """Small additive SQLite migrations for add-on upgrades.

    SQLAlchemy create_all does not add columns to existing tables. HA add-on
    users keep the same DB across updates, so we handle additive columns here.
    """
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "automation_draft" in tables:
        _add_missing_columns("automation_draft", {
            "installed_id": "VARCHAR(255) DEFAULT ''",
            "installed_path": "VARCHAR(512) DEFAULT ''",
            "installed_at": "DATETIME",
            "install_error": "TEXT DEFAULT ''",
        })
    if "command_log" in tables:
        _add_missing_columns("command_log", {
            "conversation_id": "VARCHAR(128) DEFAULT ''",
            "tool_call": "TEXT DEFAULT '{}'",
            "resolved": "TEXT DEFAULT '{}'",
            "data": "TEXT DEFAULT '{}'",
            "error": "TEXT DEFAULT ''",
        })


def _add_missing_columns(table: str, additions: dict[str, str]) -> None:
    inspector = inspect(engine)
    existing = {col["name"] for col in inspector.get_columns(table)}
    with engine.begin() as conn:
        for name, ddl in additions.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def get_session() -> Session:
    return SessionLocal()
