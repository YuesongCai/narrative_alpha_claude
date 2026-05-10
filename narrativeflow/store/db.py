"""SQLAlchemy engine + session factory.

The engine is built once from `Settings.database_url` and reused for the
process. `init_db` creates tables if they don't exist — fine for V1; for V3+
we'll switch to Alembic migrations.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from ..models import Base


_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _ensure_engine() -> tuple[Engine, sessionmaker[Session]]:
    global _engine, _SessionFactory
    if _engine is None or _SessionFactory is None:
        settings = get_settings()
        kwargs: dict = {"future": True}
        if settings.database_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(settings.database_url, **kwargs)
        _SessionFactory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine, _SessionFactory


def init_db() -> None:
    engine, _ = _ensure_engine()
    Base.metadata.create_all(engine)


def SessionLocal() -> Session:  # noqa: N802 — keep FastAPI-style name
    _, factory = _ensure_engine()
    return factory()


@contextmanager
def get_session() -> Iterator[Session]:
    """Context-managed session. Commits on success, rolls back on exception."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
