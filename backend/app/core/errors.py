from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _message(detail: object, fallback: str) -> str:
    if isinstance(detail, str):
        return detail
    return fallback


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        message = _message(exc.detail, "HTTP error")
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "detail": message,
                "error": {
                    "code": f"http_{exc.status_code}",
                    "message": message,
                },
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Validation error",
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "fields": exc.errors(),
                },
            },
        )

