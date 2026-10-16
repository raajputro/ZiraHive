"""The few GharBox API calls the sync client needs."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import httpx

USER_AGENT = "GharBox Sync"


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None):
        super().__init__(message)
        self.status, self.code = status, code


class SignedOut(ApiError):
    pass


def _raise(r: httpx.Response) -> None:
    if r.is_success:
        return
    try:
        detail = r.json().get("detail")
    except Exception:
        detail = r.text[:200]
    code = None
    if isinstance(detail, dict):
        code, detail = detail.get("code"), detail.get("message")
    cls = SignedOut if r.status_code == 401 else ApiError
    raise cls(r.status_code, str(detail or r.reason_phrase), code)


class Api:
    def __init__(self, server: str, token: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        headers = {"User-Agent": USER_AGENT}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.AsyncClient(base_url=server.rstrip("/"), headers=headers, transport=transport,
                                      timeout=httpx.Timeout(60, connect=15), follow_redirects=True)
        self.chunk = 8 * 1024 * 1024

    async def close(self) -> None:
        await self.http.aclose()

    async def login(self, username: str, password: str, code: str | None = None) -> str:
        """Signs in and swaps the session for a long-lived device sign-in. Returns the token."""
        r = await self.http.post("/api/auth/login", json={"username": username, "password": password, "code": code})
        _raise(r)
        self.http.headers["Authorization"] = f"Bearer {r.json()['token']}"
        r = await self.http.post("/api/auth/device-token")
        _raise(r)
        token = r.json()["token"]
        self.http.headers["Authorization"] = f"Bearer {token}"
        return token

    async def me(self) -> dict:
        r = await self.http.get("/api/auth/me")
        _raise(r)
        return r.json()

    async def configure(self) -> None:
        r = await self.http.get("/api/config")
        if r.is_success:
            mb = r.json().get("max_chunk_mb") or 8
            self.chunk = max(256 * 1024, min(mb, 16) * 1024 * 1024)

    async def tree(self, root: str) -> dict:
        r = await self.http.get("/api/sync/tree", params={"root": root})
        _raise(r)
        return r.json()

    async def make_folder(self, path: str) -> None:
        _raise(await self.http.post("/api/folders", json={"path": path}))

    async def upload(self, src: Path, folder: str, name: str, sha256: str,
                     progress: Callable[[int], None] | None = None) -> dict:
        size = src.stat().st_size
        r = await self.http.post("/api/uploads", json={"filename": name, "size": size, "folder": folder,
                                                       "sha256": sha256, "dedupe": False, "replace": True})
        _raise(r)
        up = r.json()
        offset = up.get("offset", 0)
        with open(src, "rb") as f:
            while up.get("status") == "uploading":
                f.seek(offset)
                data = f.read(self.chunk)
                r = await self.http.patch(f"/api/uploads/{up['id']}", content=data, headers={"Upload-Offset": str(offset)})
                if r.status_code == 409 and "Upload-Offset" in r.headers:  # resume where the server is
                    offset = int(r.headers["Upload-Offset"])
                    continue
                _raise(r)
                res = r.json()
                offset = res.get("offset", offset + len(data))
                if progress:
                    progress(offset)
                if res.get("status") != "uploading":
                    return res["asset"]
        return up["asset"]

    async def download(self, asset_id: str, dest: Path) -> None:
        tmp = dest.with_name(f".gharbox-sync-{os.getpid()}-{dest.name}.tmp")
        try:
            async with self.http.stream("GET", f"/api/assets/{asset_id}/file", params={"download": "true"}) as r:
                if not r.is_success:
                    await r.aread()
                    _raise(r)
                with open(tmp, "wb") as f:
                    async for block in r.aiter_bytes(1024 * 1024):
                        f.write(block)
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)

    async def trash(self, asset_id: str) -> None:
        r = await self.http.delete(f"/api/assets/{asset_id}")
        if r.status_code != 404:  # already gone is fine
            _raise(r)


def dlna_fetcher(server: str, token: str, transport: httpx.BaseTransport | None = None):
    """A plain (not async) folder fetcher for the TV server, which answers TVs from threads."""
    http = httpx.Client(base_url=server.rstrip("/"), transport=transport, timeout=30, follow_redirects=True,
                        headers={"User-Agent": USER_AGENT, "Authorization": f"Bearer {token}"})

    def fetch(folder_id: str) -> dict:
        r = http.get("/api/dlna/browse", params={"id": folder_id})
        _raise(r)
        return r.json()

    return fetch
