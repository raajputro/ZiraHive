"""HTTP Range support so video players can seek and downloads can resume."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

import aiofiles
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

CHUNK = 1024 * 1024
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


def _content_disposition(filename: str, inline: bool) -> str:
    kind = "inline" if inline else "attachment"
    ascii_name = filename.encode("ascii", "ignore").decode() or "file"
    ascii_name = ascii_name.replace('"', "")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def ranged_file_response(request: Request, path: Path, media_type: str,
                         filename: str | None = None, inline: bool = True) -> StreamingResponse:
    if not path.is_file():
        raise HTTPException(404, "File is missing on disk")
    size = path.stat().st_size
    start, end = 0, size - 1
    status = 200
    header = request.headers.get("range")
    if header:
        m = _RANGE.fullmatch(header.strip())
        if not m or (m.group(1) == "" and m.group(2) == ""):
            raise HTTPException(416, "Bad range", headers={"Content-Range": f"bytes */{size}"})
        if m.group(1) == "":  # suffix range: last N bytes
            start = max(size - int(m.group(2)), 0)
        else:
            start = int(m.group(1))
            if m.group(2):
                end = min(int(m.group(2)), size - 1)
        if start >= size or start > end:
            raise HTTPException(416, "Range not satisfiable",
                                headers={"Content-Range": f"bytes */{size}"})
        status = 206

    async def body():
        async with aiofiles.open(path, "rb") as f:
            await f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                data = await f.read(min(CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1)}
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    if filename:
        headers["Content-Disposition"] = _content_disposition(filename, inline)
    return StreamingResponse(body(), status_code=status, media_type=media_type, headers=headers)
