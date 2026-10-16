from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from . import db
from .config import get_settings
from .models import Library
from .routers import admin, auth, files, media, uploads
from .services import jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("gharbox")

VERSION = "0.1.0"


async def bootstrap_libraries() -> None:
    """Create the libraries listed in GHARBOX_MEDIA_LIBRARIES on first start."""
    async with db.sessionmaker()() as session:
        for name, path, kind in get_settings().parsed_libraries():
            if not await session.scalar(select(Library.id).where(Library.path == path)):
                lib = Library(name=name, path=path, kind=kind)
                session.add(lib)
                await session.commit()
                log.info("added library %s -> %s", name, path)
                await jobs.enqueue("scan_library", lib.id)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    settings.resolved_secret()
    db.init_engine(settings.db_url)
    await db.create_all()
    await jobs.init_queue()
    await bootstrap_libraries()
    log.info("GharBox %s ready (data: %s)", VERSION, settings.data_dir.resolve())
    yield
    await jobs.close_queue()
    await db.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="GharBox", version=VERSION, lifespan=lifespan,
                  description="Self-hosted backup and media server")
    origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"],
                           expose_headers=["Upload-Offset", "Content-Range"])
    for r in (auth.router, uploads.router, files.router, media.router, admin.router):
        app.include_router(r)

    @app.get("/api/health", tags=["system"])
    async def health() -> dict:
        return {"status": "ok", "version": VERSION}

    return app


app = create_app()
