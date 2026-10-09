"""The custom rail's stored artifact (#39, ADR-0018 D7-D11).

The library validates and hashes a recipe; this module only decides which
rail a posted document is on and holds the one rule open, paint and refresh share (save no longer refuses, #63):
a recipe that pins any library is refused (library-pin resolution is a later
slice).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chartagent import ChartRecipe


class PinnedLibrariesError(Exception):
    """Studio's own refusal: the recipe's document pins third-party
    libraries, which this slice cannot resolve."""

    def __init__(self, libraries: list[str]) -> None:
        super().__init__(
            "This chart uses third-party libraries, which Studio can't "
            "load yet: " + ", ".join(libraries)
        )
        self.libraries = libraries


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


def ensure_supported(recipe: ChartRecipe) -> None:
    pinned = [pin.name for pin in recipe.document.libraries]
    if pinned:
        raise PinnedLibrariesError(pinned)
