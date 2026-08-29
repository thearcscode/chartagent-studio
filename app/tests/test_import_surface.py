"""The app consumes chartagent as an external consumer does: the declared
dependency, resolved by uv — never a vendored copy or a sys.path sibling hack."""

from pathlib import Path

import chartagent  # noqa: F401

import studio  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[2]

PUBLIC_API = (
    "bind",
    "Envelope",
    "DataSource",
    "Advisory",
    "flint_bundle",
    "FlintBundle",
    "ChartAgentError",
    "canonical_json",
    "vocabulary",
    "ChartVocabulary",
    "InputFrame",
    "Backend",
)


def test_chartagent_public_api_is_importable() -> None:
    for name in PUBLIC_API:
        assert hasattr(chartagent, name), f"chartagent.{name} is not importable"


def test_chartagent_is_not_a_vendored_copy_inside_this_repo() -> None:
    chartagent_file = Path(chartagent.__file__ or "").resolve()
    assert not chartagent_file.is_relative_to(REPO_ROOT), (
        f"chartagent resolves inside the Studio repo ({chartagent_file}); "
        "it must come from the declared dependency"
    )
