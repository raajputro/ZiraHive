from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str) -> AsyncEngine:
    global _engine, _sessionmaker
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"timeout": 30}
    _engine = create_async_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(_engine.sync_engine, "connect")
        def _pragmas(conn, _):  # pragma: no cover - trivial
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    assert _sessionmaker is not None, "database not initialised"
    return _sessionmaker


async def create_all() -> None:
    from . import models  # noqa: F401  (register tables)

    assert _engine is not None
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose() -> None:
    if _engine is not None:
        await _engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as session:
        yield session
