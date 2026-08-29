from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from jwt import PyJWKClient
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from studio.config import Settings
from studio.routes import health, session


class SpaStaticFiles(StaticFiles):
    """Static files with an SPA fallback: unknown client-side routes serve
    index.html so the router can take over. Paths that look like files (they
    carry an extension) 404 honestly."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
            if response.status_code != 404:
                return response
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
        if _looks_like_file(path):
            raise StarletteHTTPException(status_code=404)
        return await super().get_response("index.html", scope)


def _looks_like_file(path: str) -> bool:
    return "." in path.rsplit("/", 1)[-1]


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        # Reads CLERK_JWKS_URL from the environment; pydantic-settings fields
        # are env-populated, which mypy cannot see.
        settings = Settings()  # type: ignore[call-arg]

    # SPA-private routes: no API keys, no OpenAPI promise, no versioned paths.
    app = FastAPI(
        title="Chartagent Studio",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    # Fetches the JWKS document once and caches it; no Clerk API call per request.
    app.state.jwks_client = PyJWKClient(settings.clerk_jwks_url, cache_keys=True)

    app.include_router(health.router, prefix="/api")
    app.include_router(session.router, prefix="/api")

    if settings.web_dist_dir.is_dir():
        app.mount(
            "/",
            SpaStaticFiles(directory=settings.web_dist_dir, html=True),
            name="spa",
        )
    return app
