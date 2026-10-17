"""Alembic: database changes between ZiraHive versions.

ZiraHive runs these by itself at start-up (app/db.py). To make a new one after changing
app/models.py:   cd server;  alembic revision --autogenerate -m "what changed"
then read the file it writes and fix anything autogenerate can't know (renames, data moves).
"""
from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app import models  # noqa: F401  (register the tables)
from app.config import get_settings
from app.db import Base

target_metadata = Base.metadata


def run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata,
                      render_as_batch=connection.dialect.name == "sqlite",  # SQLite can't ALTER much
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:  # called by ZiraHive at start-up, on its own connection
    run(connection)
else:  # the alembic command line
    async def main() -> None:
        engine = create_async_engine(get_settings().db_url)
        async with engine.begin() as conn:
            await conn.run_sync(run)
        await engine.dispose()

    asyncio.run(main())
