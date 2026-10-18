"""Batch 9: database migrations (SQLite, and Postgres when TEST_POSTGRES_URL is set), health check."""
from __future__ import annotations

import os

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app import db
from app.db import Base

PG = os.environ.get("TEST_POSTGRES_URL")  # e.g. postgresql+asyncpg://zirahive:zirahive@localhost:5433/zirahive


def drift(conn) -> list:
    """Differences between the models and the migrated database: must be none, or a migration
    is missing (cd server; alembic revision --autogenerate -m '...')."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    ctx = MigrationContext.configure(conn, opts={"compare_type": True})
    return compare_metadata(ctx, Base.metadata)


async def _fresh(url: str) -> None:
    from app import models  # noqa: F401

    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                await conn.exec_driver_sql("DROP SCHEMA public CASCADE")
                await conn.exec_driver_sql("CREATE SCHEMA public")
            await conn.run_sync(db.migrate)
            assert await conn.run_sync(db.schema_version) == "0002"
            assert await conn.run_sync(drift) == []
            await conn.run_sync(db.migrate)  # a second start changes nothing
    finally:
        await engine.dispose()


async def test_migrations_build_the_whole_schema_sqlite(tmp_path):
    await _fresh(f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}")


@pytest.mark.skipif(not PG, reason="set TEST_POSTGRES_URL to test on Postgres")
async def test_migrations_build_the_whole_schema_postgres():
    await _fresh(PG)


async def test_a_database_from_before_migrations_is_caught_up(tmp_path):
    from app import models  # noqa: F401

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'old.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # as an older version left it: a newer column missing, someone's data in it
        await conn.exec_driver_sql("DROP INDEX ix_assets_phash")
        await conn.exec_driver_sql("ALTER TABLE assets DROP COLUMN phash")
        await conn.exec_driver_sql("INSERT INTO users (id, username, password_hash, is_admin, token_version, "
                                   "totp_enabled, created_at) VALUES ('u1', 'mahbub', 'x', 1, 0, 0, '2026-01-01')")
    async with engine.begin() as conn:
        await conn.run_sync(db.migrate)
        cols = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("assets")})
        assert "phash" in cols
        assert await conn.run_sync(db.schema_version) == "0002"
        assert (await conn.execute(text("SELECT username FROM users"))).scalar() == "mahbub"
    await engine.dispose()


async def test_health_check(client, admin):
    checks = {c["id"]: c for c in (await client.get("/api/admin/health")).json()}
    assert checks["version"]["detail"] == "1.0.0"
    assert checks["database"]["status"] == "ok" and "schema 0002" in checks["database"]["detail"]
    assert checks["storage"]["status"] in ("ok", "warn")
    assert checks["lan"]["status"] == "warn" and checks["lan"]["fix"]
    assert all(c["status"] in ("ok", "warn", "fail", "info") for c in checks.values())
    client.headers.pop("Authorization")
    client.cookies.clear()
    assert (await client.get("/api/admin/health")).status_code == 401


async def test_saving_a_position_many_times_at_once(client, admin, tmp_path):
    import asyncio

    from app.services import jobs
    from conftest import make_video

    make_video(tmp_path / "films" / "Monpura (2009).mp4", seconds=2)
    await client.post("/api/libraries", json={"name": "Films", "path": str(tmp_path / "films"), "kind": "movies"})
    await jobs.drain_local()
    film = (await client.get("/api/media")).json()[0]
    results = await asyncio.gather(*(client.put(f"/api/media/{film['id']}/progress", json={"position": 0.5 + i / 10})
                                     for i in range(10)))
    assert {r.status_code for r in results} == {204}
    assert (await client.get(f"/api/media/{film['id']}")).json()["position"] > 0
