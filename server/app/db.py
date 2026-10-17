from __future__ import annotations

from collections.abc import AsyncIterator

import logging

from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


log = logging.getLogger(__name__)


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
        if conn.dialect.name == "postgresql":
            # api and worker start at the same time; let only one create/upgrade tables.
            await conn.exec_driver_sql("SELECT pg_advisory_xact_lock(424242)")
        # Runs first, while no table references assets yet (album_items etc. are created
        # below), so rebuilding the table on SQLite can't break anyone's foreign keys.
        await conn.run_sync(drop_asset_hash_unique)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(add_missing_columns)


def add_missing_columns(conn) -> None:
    """Upgrade an existing database in place: add columns and indexes that newer versions
    of ZiraHive define but the database doesn't have yet. New tables are already handled by
    create_all. (Renames and type changes will need proper migrations; see ROADMAP.)"""
    insp = inspect(conn)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(dialect=conn.dialect)}'
            if col.server_default is not None:
                arg = col.server_default.arg
                default = (f"'{arg}'" if isinstance(arg, str) else
                           str(arg.compile(dialect=conn.dialect, compile_kwargs={"literal_binds": True})))
                ddl += f" DEFAULT {default}"
            conn.exec_driver_sql(ddl)
            log.info("database upgraded: added %s.%s", table.name, col.name)
        index_names = {i["name"] for i in inspect(conn).get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in index_names:
                index.create(conn, checkfirst=True)


async def dispose() -> None:
    if _engine is not None:
        await _engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as session:
        yield session


def drop_asset_hash_unique(conn) -> None:
    """v0.1 allowed one copy of a file per account. Files may now hold copies in several
    folders (photo backup still skips duplicates), so the unique rule is removed."""
    insp = inspect(conn)
    if not insp.has_table("assets"):
        return
    uniques = [u for u in insp.get_unique_constraints("assets")
               if sorted(u["column_names"]) == ["owner_id", "sha256"]]
    if not uniques:
        return
    if conn.dialect.name == "postgresql":
        for u in uniques:
            conn.exec_driver_sql(f'ALTER TABLE assets DROP CONSTRAINT "{u["name"]}"')
    else:  # SQLite can't drop a constraint: rebuild the table
        table = Base.metadata.tables["assets"]
        cols = ", ".join(c["name"] for c in insp.get_columns("assets"))
        # legacy_alter_table keeps other tables' foreign keys pointing at "assets" (the new
        # table) instead of following the rename to assets_v1.
        conn.exec_driver_sql("PRAGMA legacy_alter_table=ON")
        for idx in insp.get_indexes("assets"):
            conn.exec_driver_sql(f'DROP INDEX IF EXISTS "{idx["name"]}"')
        conn.exec_driver_sql("ALTER TABLE assets RENAME TO assets_v1")
        table.create(conn)
        conn.exec_driver_sql(f"INSERT INTO assets ({cols}) SELECT {cols} FROM assets_v1")
        conn.exec_driver_sql("DROP TABLE assets_v1")
        conn.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
    log.info("database upgraded: files may now have copies in several folders")
