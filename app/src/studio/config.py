from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


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
