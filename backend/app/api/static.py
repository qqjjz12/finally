"""Static frontend serving (Next.js export) with SPA fallback."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from .errors import error_response


def static_dir() -> Path | None:
    env = os.environ.get("FINALLY_STATIC_DIR")
    path = Path(env) if env else Path(__file__).resolve().parents[2] / "static"
    return path if path.is_dir() else None


def mount_static(app: FastAPI) -> None:
    """Register last so /api routes win."""
    root = static_dir()
    if root is None:
        return
    root = root.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def serve(path: str):
        if path == "api" or path.startswith("api/"):
            return error_response(404, "not_found", "Not found")
        for candidate in (path, f"{path}.html", f"{path}/index.html"):
            if not candidate or candidate.endswith("/"):
                continue
            target = (root / candidate).resolve()
            if target.is_file() and root in target.parents:
                return FileResponse(target)
        index = root / "index.html"
        if index.is_file():
            return FileResponse(index)
        return error_response(404, "not_found", "Not found")
