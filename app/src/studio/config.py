import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Vendor API keys are not Settings fields — the name is derived from
# PLANNER_MODEL's prefix. Load `.env` into the process so a key written
# next to CLERK_JWKS_URL is visible to both the boot check and the provider.
load_dotenv()


class StudioConfigurationError(Exception):
    """Studio cannot start: a setting the operator owns is missing or wrong."""


def provider_api_key_name(model: str) -> str:
    """The vendor env var implied by a pydantic-ai model string's prefix."""
    return f"{model.split(':', 1)[0].upper()}_API_KEY"


def require_planner_api_key(model: str) -> None:
    """Raise before the agent is built, so a missing key is Studio's fault."""
    env_name = provider_api_key_name(model)
    if not os.environ.get(env_name):
        raise StudioConfigurationError(
            f"PLANNER_MODEL={model!r} requires the {env_name} environment variable"
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Clerk session verification. The JWKS document is fetched once and cached;
    # no Clerk API call happens per request.
    clerk_jwks_url: str
    clerk_authorized_parties: list[str] = []
    # Clerk session tokens carry the instance's Frontend API domain as `iss`.
    # Optional because the JWKS URL already pins the instance; set it to verify.
    clerk_issuer: str | None = None
    jwt_leeway_seconds: float = 30.0

    web_dist_dir: Path = _REPO_ROOT / "web" / "dist"

    # Managed Postgres in deploys; the compose db service in dev (ADR-0007 D1).
    database_url: str = "postgresql+psycopg://studio:studio@localhost:5432/studio"
    # Dev implementation of the object-store seam; the vendor is deliberately
    # unchosen (ADR-0006 D10). Relative to the process working directory.
    object_store_dir: Path = Path(".objects")
    # The four caps are configuration, never literals (ADR-0006 D9).
    upload_max_bytes: int = 50 * 1024 * 1024
    # A bind whose transform output exceeds this raises rather than
    # truncates — the app never silently ships a subset.
    bind_row_cap: int = 100_000
    # Passed through to the library's `bind` timeout kwarg — the one cap
    # that guards DuckDB's own execution.
    bind_timeout_seconds: float = 30.0
    # Backstop for the whole request; must exceed the bind timeout.
    request_timeout_seconds: float = 120.0
    # Concurrent plans (Studio ADR-0001 D8). A plan is seconds long and a
    # different tenant of the threadpool than a millisecond bind.
    plan_concurrency: int = 2
    # pydantic-ai model string; the provider prefix names the API-key env var
    # (Studio ADR-0002). Bare, matching bind_row_cap — no STUDIO_ prefix.
    planner_model: str = "anthropic:claude-sonnet-5"
