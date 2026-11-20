"""FastAPI application factory with loopback-only browser and host checks."""

import hashlib
import threading
from collections.abc import AsyncGenerator, AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import HTMLResponse, StreamingResponse

from stridelog.api.activities import router as activities_router
from stridelog.api.analytics import router as analytics_router
from stridelog.api.sync import router as sync_router
from stridelog.api.sync import run_sync_pipeline
from stridelog.config import Settings
from stridelog.db.engine import database_engine
from stridelog.errors import StridelogError

ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
)
SWAGGER_ASSET_DIRECTORY = Path(str(files("swagger_ui").joinpath("static")))
SWAGGER_ASSET_PATHS = {
    asset_name: SWAGGER_ASSET_DIRECTORY / asset_name
    for asset_name in ("favicon-32x32.png", "swagger-ui-bundle.js", "swagger-ui.css")
}


def _is_allowed_host(value: str) -> bool:
    if not value or value != value.strip() or any(character.isspace() for character in value):
        return False
    try:
        parsed = urlsplit(f"//{value}")
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    return (
        hostname is not None
        and hostname.lower() in ALLOWED_HOSTS
        and parsed.username is None
        and parsed.password is None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and port in {None, 8000}
    )


def _body_bytes(chunk: object) -> bytes:
    if isinstance(chunk, bytes):
        return chunk
    if isinstance(chunk, str):
        return chunk.encode()
    if isinstance(chunk, memoryview):
        return chunk.tobytes()
    raise TypeError("ASGI response yielded an unsupported body chunk.")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    yield
    app.state.executor.shutdown(wait=True, cancel_futures=True)
    app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct the API without initializing storage or contacting Garmin."""
    selected_settings = settings or Settings()
    app = FastAPI(
        title="stridelog Local API",
        version="1.0.0",
        description="Local-only API for running activities and analytics.",
        docs_url=None,
        redoc_url=None,
        lifespan=_lifespan,
    )
    app.state.settings = selected_settings
    app.state.engine = database_engine(selected_settings.data_dir)
    app.state.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stridelog-sync")
    app.state.sync_lock = threading.Lock()
    app.state.sync_job_id = None
    app.state.sync_future = None
    app.state.sync_runner = run_sync_pipeline

    app.include_router(activities_router)
    app.include_router(analytics_router)
    app.include_router(sync_router)

    @app.get("/docs", include_in_schema=False)
    def swagger_docs() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title="stridelog Local API",
            swagger_js_url="/swagger-ui/swagger-ui-bundle.js",
            swagger_css_url="/swagger-ui/swagger-ui.css",
            swagger_favicon_url="/swagger-ui/favicon-32x32.png",
        )

    @app.get("/swagger-ui/{asset_name}", include_in_schema=False)
    def swagger_asset(asset_name: str) -> FileResponse:
        asset_path = SWAGGER_ASSET_PATHS.get(asset_name)
        if asset_path is None:
            raise HTTPException(status_code=404, detail="Swagger asset not found.")
        return FileResponse(asset_path)

    app.add_middleware(GZipMiddleware, minimum_size=500)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ALLOWED_ORIGINS),
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "If-None-Match"],
        expose_headers=["ETag"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def enforce_local_request(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        host = request.headers.get("host", "")
        if not _is_allowed_host(host):
            return JSONResponse({"detail": "Unknown Host header."}, status_code=400)
        origin = request.headers.get("origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            return JSONResponse({"detail": "Browser origin is not allowed."}, status_code=403)
        if request.url.path.startswith("/api/v1") and request.method in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].strip()
            if content_type != "application/json":
                return JSONResponse(
                    {"detail": "Changes must use application/json."}, status_code=415
                )

        response: Response = await call_next(request)
        if (
            not request.url.path.startswith("/api/v1")
            or request.method not in {"GET", "HEAD"}
            or response.status_code != 200
        ):
            return response
        stream = cast("StreamingResponse", response)
        chunks: list[bytes] = []
        async for chunk in cast("AsyncIterator[object]", stream.body_iterator):
            chunks.append(_body_bytes(chunk))
        body = b"".join(chunks)
        etag = f'W/"{hashlib.sha256(body).hexdigest()}"'
        response_etags = {
            value.strip() for value in request.headers.get("if-none-match", "").split(",")
        }
        headers = dict(response.headers)
        headers["ETag"] = etag
        headers["Cache-Control"] = "private, no-cache"
        if etag in response_etags or etag[2:] in response_etags or "*" in response_etags:
            return Response(
                status_code=304,
                headers={"ETag": etag, "Cache-Control": "private, no-cache"},
            )
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            background=response.background,
        )

    @app.exception_handler(StridelogError)
    async def handle_local_error(_request: Request, error: StridelogError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(error)})

    return app


def openapi_schema() -> dict[str, object]:
    """Return the deterministic OpenAPI schema without opening storage."""
    settings = Settings.model_construct(
        data_dir=Path.home() / ".stridelog",
        activity_lookback_days=7,
        wellness_lookback_days=3,
        request_interval_s=1.0,
        running_activity_types=("running",),
        api_key_expires_on=None,
        hr_armband_from=None,
        garmin_personal_api_key=None,
    )
    app = create_app(settings)
    schema = app.openapi()
    app.state.executor.shutdown(wait=True, cancel_futures=True)
    app.state.engine.dispose()
    return schema


__all__ = ["create_app", "openapi_schema"]
