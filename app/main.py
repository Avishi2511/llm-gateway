import logging
import secrets
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import chat, meta
from app.auth import KeyAuthenticator
from app.config import Settings, get_settings
from app.db.repo import UsageRepository
from app.db.session import create_session_factory
from app.errors import GatewayError
from app.gateway.service import GatewayService
from app.providers.registry import build_providers
from app.ratelimit import RateLimiter

logger = logging.getLogger("gateway")


def _new_request_id() -> str:
    return "req_" + secrets.token_hex(8)


def _error(request: Request, code: str, message: str, status: int, headers: dict[str, str] | None = None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or _new_request_id()
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
        headers={**(headers or {}), "X-Request-ID": request_id},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(title="SecureLLM Gateway", version="0.1.0")
    app.state.settings = settings
    app.state.providers = build_providers(settings)
    if not settings.api_keys:
        raise ValueError("GATEWAY_API_KEYS must contain at least one key")
    app.state.authenticator = KeyAuthenticator(settings.api_keys)
    app.state.session_factory = create_session_factory(settings.database_url)
    app.state.repo = UsageRepository(app.state.session_factory)
    app.state.limiter = RateLimiter(settings.rate_limit_per_minute)
    app.state.service = GatewayService(
        settings, app.state.providers, limiter=app.state.limiter, repo=app.state.repo
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = _new_request_id()
        request.state.started_at = time.perf_counter()
        # Cheap early rejection via Content-Length; per-message limits are enforced in the service
        # for clients that send no Content-Length (e.g. chunked uploads).
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_request_bytes:
            return _error(request, "REQUEST_TOO_LARGE", "The request exceeds the maximum allowed size.", 413)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(GatewayError)
    async def gateway_error_handler(request: Request, exc: GatewayError):
        if exc.code == "UNAUTHORIZED":
            logger.warning("auth_failed request_id=%s", request.state.request_id)
        return _error(request, exc.code, exc.public_message, exc.status_code, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        # Report field locations only; never echo submitted values.
        fields = sorted({".".join(str(p) for p in e["loc"] if p != "body") for e in exc.errors()} - {""})
        message = "The request is invalid."
        if fields:
            message += " Check fields: " + ", ".join(fields)
        key_id = getattr(request.state, "key_id", None)
        if key_id and request.url.path == "/v1/chat/completions":
            # Authenticated request that failed schema validation: still worth a usage row.
            app.state.service.record_invalid(request.state.request_id, key_id, request.state.started_at)
        return _error(request, "INVALID_REQUEST", message, 422)

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return _error(request, "NOT_FOUND", "Resource not found.", 404)
        return _error(request, "INVALID_REQUEST", "The request could not be processed.", exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        # Log the exception type only: messages may contain sensitive content.
        logger.error("unhandled_error type=%s", type(exc).__name__)
        return _error(request, "INTERNAL_ERROR", "An internal error occurred.", 500)

    app.include_router(meta.router)
    app.include_router(chat.router)
    return app


def get_app() -> FastAPI:
    return create_app()
