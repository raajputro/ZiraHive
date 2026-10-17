"""Health check from the command line, for when the web page doesn't open:

    docker compose exec api python -m app.doctor
"""
from __future__ import annotations

import asyncio
import sys

MARK = {"ok": "  OK  ", "warn": " WARN ", "fail": " FAIL ", "info": " info "}


async def main() -> int:
    from . import db
    from .config import get_settings
    from .services.health import run_checks

    s = get_settings()
    db.init_engine(s.db_url)
    try:
        async with db.sessionmaker()() as session:
            checks = await run_checks(session)
    finally:
        await db.dispose()
    for c in checks:
        print(f"[{MARK[c.status]}] {c.title}: {c.detail}")
        if c.fix:
            print(f"          -> {c.fix}")
    return 1 if any(c.status == "fail" for c in checks) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
