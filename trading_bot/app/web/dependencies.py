"""FastAPI dependency wiring. The dashboard is a separate process from the
Trading Engine -- it never imports a live broker or engine instance, only
ever reads the shared SQLite database (WAL mode lets both processes touch
it concurrently, per the Stage 6 design).

The engine/session factory are built lazily (on first real request), not
at import time -- importing this module (e.g. transitively, by importing
app.web.main in a test) must never have the side effect of creating a
database file on disk. Tests override get_session entirely via FastAPI's
dependency_overrides, so the lazy factory below never even runs there.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.database.session import create_db_engine, make_session_factory


@lru_cache
def _get_session_factory():
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    return make_session_factory(engine)


def get_session():
    session = _get_session_factory()()
    try:
        yield session
    finally:
        session.close()
