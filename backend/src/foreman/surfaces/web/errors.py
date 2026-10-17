"""Erreurs HTTP opaques : `{"error": "<code>"}`, sans écho de la saisie ni détail interne."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from foreman.surfaces.web.schemas import ErrorCode

CODES: dict[int, ErrorCode] = {
    404: "not_found",
    405: "method_not_allowed",
    409: "turn_in_progress",
    422: "invalid_request",
    501: "not_implemented",
    503: "capacity_exceeded",
}


class ApiError(Exception):
    def __init__(self, status: int, code: ErrorCode) -> None:
        self.status = status
        self.code = code


def error_response(
    status: int, code: ErrorCode, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code}, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, __: RequestValidationError) -> JSONResponse:
        return error_response(422, "invalid_request")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(
            exc.status_code,
            CODES.get(exc.status_code, "internal_error"),
            headers=dict(exc.headers) if exc.headers else None,
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, __: Exception) -> JSONResponse:
        return error_response(500, "internal_error")
