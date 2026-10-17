from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

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


MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


async def create_all() -> None:
    """Brings the database up to date at start-up (Alembic migrations in server/migrations)."""
    from . import models  # noqa: F401  (register tables)

    assert _engine is not None
    async with _engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            # api and worker start at the same time; let only one create/upgrade tables.
            await conn.exec_driver_sql("SELECT pg_advisory_xact_lock(424242)")
        await conn.run_sync(migrate)


def _alembic(conn):
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["connection"] = conn
    return cfg


def schema_version(conn) -> str | None:
    from alembic.runtime.migration import MigrationContext

    return MigrationContext.configure(conn).get_current_revision()


def migrate(conn) -> None:
    from alembic import command

    for name in ("alembic", "alembic.runtime.migration", "alembic.runtime.plugins"):
        logging.getLogger(name).setLevel(logging.WARNING)  # only real news in the log
    cfg = _alembic(conn)
    insp = inspect(conn)
    if schema_version(conn) is None and any(insp.has_table(t) for t in Base.metadata.tables):
        # Made before ZiraHive used migrations: catch it up the old way once (new tables, new
        # columns), then mark it as current. From here on only migrations change it.
        # (drop_asset_hash_unique runs first, while no table references assets yet.)
        drop_asset_hash_unique(conn)
        Base.metadata.create_all(conn)
        add_missing_columns(conn)
        command.stamp(cfg, "head")
        log.info("database: now upgraded by migrations")
    command.upgrade(cfg, "head")


def add_missing_columns(conn) -> None:
    """Catches up a database made before migrations existed: adds columns and indexes newer
    versions define but the database doesn't have yet. Used once per such database."""
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


async def one_row(session: AsyncSession, model, **keys):
    """The row with these key values, made first if it doesn't exist. Safe when two requests
    arrive at once (saving a position twice a second, say): the database settles who makes it."""
    from sqlalchemy import select

    row = await session.scalar(select(model).filter_by(**keys))
    if row is not None:
        return row
    conn = await session.connection()
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    await session.execute(insert(model).values(**keys).on_conflict_do_nothing(index_elements=list(keys)))
    return await session.scalar(select(model).filter_by(**keys).execution_options(populate_existing=True))
