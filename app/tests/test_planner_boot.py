"""The chart agent is built at boot (Studio ADR-0002, #18).

Seam: `create_app`. The agent is constructed once during app creation;
a missing provider key is a Studio configuration error, and a missing
vendor extra is the library's own unavailable-client error.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chartagent import ChartAgent
from chartagent.errors import ModelClientUnavailableError

from studio.config import Settings, StudioConfigurationError
from studio.main import create_app
from tests.conftest import SigningKeys, make_app


def _settings(*, planner_model: str = "anthropic:claude-sonnet-4-6") -> Settings:
    return Settings(
        clerk_jwks_url="https://clerk.test/.well-known/jwks.json",
        web_dist_dir=Path("/definitely/not/a/dist"),
        planner_model=planner_model,
    )


def test_settings_default_planner_model_is_the_library_string() -> None:
    default = Settings.model_fields["planner_model"].default
    assert default == "anthropic:claude-sonnet-4-6"


def test_create_app_raises_when_the_planner_key_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(StudioConfigurationError, match="PLANNER_MODEL"):
        create_app(_settings())


def test_create_app_checks_the_key_named_by_the_model_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-dummy-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(StudioConfigurationError, match="PLANNER_MODEL"):
        create_app(_settings(planner_model="openai:gpt-4o"))


def test_create_app_builds_one_chart_agent_when_the_key_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-dummy-key")
    app = create_app(_settings())
    assert isinstance(app.state.chart_agent, ChartAgent)


def test_create_app_raises_the_library_error_when_the_extra_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-dummy-key")
    with pytest.raises(ModelClientUnavailableError):
        create_app(_settings(planner_model="openai:gpt-4o"))


def test_make_app_supplies_a_dummy_provider_key(
    monkeypatch: pytest.MonkeyPatch, signing: SigningKeys
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = make_app(signing.jwks)
    assert isinstance(app.state.chart_agent, ChartAgent)
