"""
Database setup (SQLAlchemy).

Locally this is a SQLite file (`local.db` in the project root) so there's
nothing to install. On Railway, DATABASE_URL points at Postgres and the exact
same code runs against it.

On startup, `init_db()` creates any missing tables AND adds any column a model
has that its existing table doesn't (see `_add_missing_columns`). That covers
the common change - adding a field - with no migration step. It never renames,
retypes or drops anything; when a change like that is needed once real data is
in Postgres, that's the point to bring in Alembic.

Every model subclasses `Base` from this file; app/models.py is imported
before `init_db()` runs (see app/main.py) so the tables get created.
"""

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{PROJECT_ROOT / 'local.db'}"
    # Railway hands out postgres:// or postgresql:// URLs; SQLAlchemy needs the
    # driver named explicitly to use psycopg 3.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Base(DeclarativeBase):
    pass


engine = create_engine(_database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

if engine.dialect.name == "sqlite":
    # SQLite ignores foreign keys (and ON DELETE CASCADE) unless asked, per
    # connection. Postgres always enforces them; make local dev behave the same.
    @event.listens_for(engine, "connect")
    def _sqlite_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys = ON")


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """ALTER TABLE ... ADD COLUMN for model columns the database doesn't have yet.

    A new column on an existing table must be nullable or have a plain string
    `server_default` (e.g. server_default=""), so existing rows get a value."""
    inspector = inspect(engine)
    quote = engine.dialect.identifier_preparer.quote
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f"ALTER TABLE {quote(table.name)} ADD COLUMN {quote(col.name)} {col.type.compile(engine.dialect)}"
                default = col.server_default.arg if col.server_default is not None else None
                if isinstance(default, str):
                    ddl += " DEFAULT '" + default.replace("'", "''") + "'"
                    if not col.nullable:
                        ddl += " NOT NULL"
                elif not col.nullable:
                    raise RuntimeError(f"New column {table.name}.{col.name} needs nullable=True or a string server_default.")
                conn.execute(text(ddl))


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one DB session per request."""
    with SessionLocal() as session:
        yield session
