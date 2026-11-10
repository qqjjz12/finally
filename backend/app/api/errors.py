"""API error type and global exception handlers (format: {"error", "code"})."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db.repository import DbError

logger = logging.getLogger(__name__)

STATUS_BY_CODE = {
    "invalid_request": 400,
    "unknown_ticker": 400,
    "insufficient_cash": 400,
    "insufficient_shares": 400,
    "not_found": 404,
    "already_exists": 409,
    "position_open": 409,
    "internal_error": 500,
}


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or STATUS_BY_CODE.get(code, 500)


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message, "code": code})


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(DbError)
    async def _db_error(_: Request, exc: DbError):
        return error_response(STATUS_BY_CODE.get(exc.code, 500), exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return error_response(400, "invalid_request", "Invalid request: " + _summarize(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return error_response(404, "not_found", "Not found")
        if exc.status_code < 500:
            return error_response(exc.status_code, "invalid_request", str(exc.detail))
        return error_response(exc.status_code, "internal_error", "Internal server error")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("Unhandled error", exc_info=exc)
        return error_response(500, "internal_error", "Internal server error")


def _summarize(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors()[:3]:
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        parts.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
    return "; ".join(parts) or "bad input"
