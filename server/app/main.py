from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from . import db
from .config import get_settings
from .models import Library
from .routers import admin, albums, auth, backup, books, scans, files, media, music, parties, playback, shares, sync, uploads, vault
from .services import jobs, transcode
from .services.libraries import discover

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("gharbox")

VERSION = "0.1.0"


async def bootstrap_libraries() -> None:
    """Add a category for every folder in the media folder, plus any listed in
    GHARBOX_MEDIA_LIBRARIES, and scan the new ones."""
    async with db.sessionmaker()() as session:
        for lib in await discover(session):
            await jobs.enqueue("scan_library", lib.id)
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
    transcode.manager.start_janitor()
    log.info("GharBox %s ready (data: %s)", VERSION, settings.data_dir.resolve())
    yield
    await transcode.manager.shutdown()
    await jobs.close_queue()
    await db.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    docs = {} if settings.api_docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="GharBox", version=VERSION, lifespan=lifespan,
                  description="Self-hosted backup and media server", **docs)

    @app.middleware("http")
    async def public_gateway_guard(request: Request, call_next):
        """Requests from the public share-link site may only reach share endpoints.
        Caddy already limits that site to /api/s/*; this is the second lock."""
        if request.headers.get("x-gharbox-gateway") == "public" and not request.url.path.startswith("/api/s/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return await call_next(request)
    origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"],
                           expose_headers=["Upload-Offset", "Content-Range"])
    for r in (auth.router, uploads.router, files.router, albums.router, shares.router,
              media.router, playback.router, parties.router, music.router, books.router, vault.router, backup.router, sync.router, scans.router, admin.router):
        app.include_router(r)

    @app.get("/api/health", tags=["system"])
    async def health() -> dict:
        return {"status": "ok", "version": VERSION}

    @app.get("/api/config", tags=["system"])
    async def public_config() -> dict:
        """What the web app needs before signing in. Nothing secret."""
        s = get_settings()
        return {"version": VERSION, "public_url": s.public_url.rstrip("/"), "max_chunk_mb": s.max_chunk_mb}

    return app


app = create_app()
