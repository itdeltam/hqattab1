"""Engine/session setup. SQLite in WAL mode per the project's confirmed
architecture -- WAL lets the dashboard (Stage 7, a separate FastAPI
process later) read the database concurrently with the trading loop
writing to it."""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import Pool

from app.database.models import Base


def create_db_engine(database_url: str, poolclass: type[Pool] | None = None) -> Engine:
    """`poolclass` is a test-only escape hatch: a plain `sqlite:///:memory:`
    engine gives each new connection (e.g. each thread FastAPI's TestClient
    dispatches a sync route to) its own separate, empty in-memory database.
    Pass `StaticPool` in tests that exercise the app across threads so
    every connection shares the same in-memory database; production code
    (a real file-based SQLite path) never needs this."""
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine_kwargs = {"connect_args": connect_args}
    if poolclass is not None:
        engine_kwargs["poolclass"] = poolclass
    engine = create_engine(database_url, **engine_kwargs)

    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    Base.metadata.create_all(engine)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
