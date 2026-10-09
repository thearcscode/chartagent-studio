"""The chart agent is built at boot (Studio ADR-0002, #18).

Seam: `create_app`. The agent is constructed once during app creation;
a missing provider key is a Studio configuration error, and a missing
vendor extra is the library's own unavailable-client error.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from chartagent import ChartAgent
from chartagent.errors import ModelClientUnavailableError
from fastapi import FastAPI

from studio.config import Settings, StudioConfigurationError
from studio.main import create_app
from tests.conftest import (
    SigningKeys,
    fake_rasteriser_builder,
    make_app,
)


def _settings(
    *,
    planner_model: str = "anthropic:claude-sonnet-4-6",
    critique_model: str = "anthropic:claude-sonnet-5",
) -> Settings:
    return Settings(
        clerk_jwks_url="https://clerk.test/.well-known/jwks.json",
        web_dist_dir=Path("/definitely/not/a/dist"),
        planner_model=planner_model,
        critique_model=critique_model,
    )


def _boot(**kwargs: str) -> FastAPI:
    return create_app(
        _settings(**kwargs), rasteriser_builder=fake_rasteriser_builder
    )


def test_settings_default_planner_model_is_the_library_string() -> None:
    default = Settings.model_fields["planner_model"].default
    assert default == "anthropic:claude-sonnet-4-6"


def test_create_app_raises_when_the_planner_key_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(StudioConfigurationError, match="PLANNER_MODEL"):
        _boot()


def test_create_app_checks_the_key_named_by_the_model_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-dummy-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(StudioConfigurationError, match="PLANNER_MODEL"):
        _boot(planner_model="openai:gpt-4o")


def test_create_app_builds_one_chart_agent_when_the_key_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-dummy-key")
    app = _boot()
    assert isinstance(app.state.chart_agent, ChartAgent)


def test_create_app_raises_the_library_error_when_the_extra_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-dummy-key")
    with pytest.raises(ModelClientUnavailableError):
        _boot(planner_model="openai:gpt-4o")


def test_make_app_supplies_a_dummy_provider_key(
    monkeypatch: pytest.MonkeyPatch, signing: SigningKeys
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = make_app(signing.jwks)
    assert isinstance(app.state.chart_agent, ChartAgent)


def test_settings_default_critique_model() -> None:
    default = Settings.model_fields["critique_model"].default
    assert default == "anthropic:claude-sonnet-5"


def test_changing_only_the_planner_model_leaves_the_critic_default() -> None:
    settings = _settings(planner_model="openai:gpt-4o")
    assert settings.critique_model == "anthropic:claude-sonnet-5"


def test_create_app_passes_the_critique_model_to_the_chart_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-dummy-key")
    calls: list[dict[str, object]] = []

    def fake_create_chart_agent(**kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr("studio.main.create_chart_agent", fake_create_chart_agent)
    _boot(critique_model="anthropic:claude-opus-5")
    assert len(calls) == 1
    assert calls[0]["model"] == "anthropic:claude-sonnet-4-6"
    assert calls[0]["critique_model"] == "anthropic:claude-opus-5"


def test_missing_critique_key_names_the_setting_and_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-dummy-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(StudioConfigurationError) as excinfo:
        _boot(critique_model="openai:gpt-4o")
    assert "CRITIQUE_MODEL" in str(excinfo.value)
    assert "OPENAI_API_KEY" in str(excinfo.value)


def test_one_anthropic_key_serves_both_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-dummy-key")
    app = _boot()
    assert isinstance(app.state.chart_agent, ChartAgent)
