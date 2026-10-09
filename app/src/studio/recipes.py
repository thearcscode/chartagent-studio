"""The custom rail's stored artifact (#39, ADR-0018 D7-D11).

The library validates and hashes a recipe; this module only decides which
rail a posted document is on. A recipe that pins libraries saves, opens,
paints and refreshes like any other (#63, #64, #65).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class RecipeOperationUnsupportedError(Exception):
    """A diff or remap over a recipe: a one-line JSON diff is not the review
    surface (ADR-0018 D9)."""

    def __init__(self) -> None:
        super().__init__(
            "This isn't supported for custom charts yet"
        )


def is_recipe(content: Mapping[str, Any]) -> bool:
    """The server decides the kind from the content, by the library's own
    rule: a mapping with a `document` key is a recipe."""
    return "document" in content
