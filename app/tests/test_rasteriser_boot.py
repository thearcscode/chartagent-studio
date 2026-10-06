"""The review rasteriser is built at boot and closed at shutdown (#55).

Seam: `create_app`, with the rasteriser builder substituted — no browser is
launched and no Flint review runs. One opt-in test boots the real thing.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studio.config import Settings, StudioConfigurationError
from studio.main import create_app
from studio.rasteriser import build_rasteriser
from tests.conftest import FakeRasteriser


def _settings(vendor_dir: Path | None = None) -> Settings:
    settings = Settings(
        clerk_jwks_url="https://clerk.test/.well-known/jwks.json",
        web_dist_dir=Path("/definitely/not/a/dist"),
    )
    if vendor_dir is not None:
        settings.renderer_vendor_dir = vendor_dir
    return settings


@pytest.fixture(autouse=True)
def _provider_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-dummy-key")


def test_create_app_passes_the_rasteriser_to_create_chart_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_create_chart_agent(**kwargs: object) -> object:
        calls.append(kwargs)
        return object()

    monkeypatch.setattr("studio.main.create_chart_agent", fake_create_chart_agent)
    rasteriser = FakeRasteriser()
    create_app(_settings(), rasteriser_builder=lambda _: rasteriser)  # type: ignore[arg-type,return-value]
    assert len(calls) == 1
    assert calls[0]["rasteriser"] is rasteriser


def test_shutdown_closes_the_rasteriser_exactly_once() -> None:
    rasteriser = FakeRasteriser()
    app = create_app(_settings(), rasteriser_builder=lambda _: rasteriser)  # type: ignore[arg-type,return-value]
    assert rasteriser.close_calls == 0
    with TestClient(app):
        assert rasteriser.close_calls == 0
    assert rasteriser.close_calls == 1


def test_default_vendor_dir_is_the_sibling_checkouts() -> None:
    default = Settings.model_fields["renderer_vendor_dir"].default
    assert default.parts[-4:] == ("chartagent", "tools", "paint", "vendor")
    assert default.parent.parent.parent.parent.name != "site-packages"


def test_missing_vendor_dir_names_the_setting(tmp_path: Path) -> None:
    with pytest.raises(StudioConfigurationError, match="RENDERER_VENDOR_DIR"):
        build_rasteriser(_settings(tmp_path / "nope"))


def test_sha_mismatch_names_the_setting(tmp_path: Path) -> None:
    vendor = _settings().renderer_vendor_dir
    shutil.copytree(vendor, tmp_path / "vendor")
    manifest_path = tmp_path / "vendor" / "vendor.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["vega"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(StudioConfigurationError, match="RENDERER_VENDOR_DIR"):
        build_rasteriser(_settings(tmp_path / "vendor"))


def _browser_installed() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            return Path(pw.chromium.executable_path).exists()
    except Exception:
        return False


@pytest.mark.skipif(not _browser_installed(), reason="no Playwright browser installed")
def test_boots_against_the_real_vendor_directory_and_closes() -> None:
    app = create_app(_settings())
    with TestClient(app):
        pass
