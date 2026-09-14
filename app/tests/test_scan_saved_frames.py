"""chartagent-studio#26: the saved-frame scan finds the one shape fault the
new chartagent.InputFrame rejects that the currently-pinned one still opens —
a transform sort item written as ``{field, order}`` instead of the now-typed
``{field, dir}`` (ADR-0023 Decision 5) — and leaves everything else alone.

`scripts/` sits outside `src/studio` on purpose (AGENTS.md: a one-off tool,
not shipped product code), so it is loaded here by path rather than import.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_APP_DIR = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "scan_saved_frames", _APP_DIR / "scripts" / "scan_saved_frames.py"
)
assert _spec is not None and _spec.loader is not None
scan_saved_frames = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = scan_saved_frames
_spec.loader.exec_module(scan_saved_frames)


class FakeScalars(list[Any]):
    pass


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._rows)


class FakeSession:
    """Enough of `Session` for `scan()`: one `execute()` returning rows."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def execute(self, *_args: Any, **_kwargs: Any) -> FakeResult:
        return FakeResult(self._rows)


def _revision(chart_id: str, revision_number: int, content: dict[str, Any]) -> Any:
    return SimpleNamespace(
        chart_id=chart_id, revision_number=revision_number, content=content
    )


_VALID_CHART_SPEC = {
    "chartType": "Bar Chart",
    "encodings": {"x": {"field": "b"}, "y": {"field": "a"}},
}


def test_old_sort_shape_fails_with_the_field_path_the_ticket_names() -> None:
    old_shape = {
        "chart_spec": _VALID_CHART_SPEC,
        "x_chartagent": {
            "transform": {"sort": [{"field": "total", "order": "desc"}]}
        },
    }
    session = FakeSession([_revision("c1", 3, old_shape)])

    scanned, failures = scan_saved_frames.scan(session)

    assert scanned == 1
    assert len(failures) == 1
    failure = failures[0]
    assert failure.chart_id == "c1"
    assert failure.revision_number == 3
    assert failure.path == "x_chartagent.transform.sort[0]"
    assert "unrecognised key(s) ('order',)" in failure.message


def test_new_sort_shape_and_a_transform_free_frame_both_pass() -> None:
    new_shape = {
        "chart_spec": _VALID_CHART_SPEC,
        "x_chartagent": {"transform": {"sort": [{"field": "total", "dir": "desc"}]}},
    }
    plain = {"chart_spec": _VALID_CHART_SPEC}
    session = FakeSession([_revision("c1", 1, new_shape), _revision("c2", 1, plain)])

    scanned, failures = scan_saved_frames.scan(session)

    assert scanned == 2
    assert failures == []


def test_report_is_read_only_of_the_credentials_and_groups_by_path() -> None:
    failures = [
        scan_saved_frames.Failure(
            chart_id="c1",
            revision_number=1,
            exception_type="SpecShapeError",
            message="x_chartagent.transform.sort[0]: unrecognised key(s) ('order',)",
            path="x_chartagent.transform.sort[0]",
        ),
        scan_saved_frames.Failure(
            chart_id="c2",
            revision_number=2,
            exception_type="SpecShapeError",
            message="x_chartagent.transform.sort[0]: unrecognised key(s) ('order',)",
            path="x_chartagent.transform.sort[0]",
        ),
    ]

    report = scan_saved_frames.render_report(
        "postgresql+psycopg://studio:secret@db.internal:5432/studio", 5, failures
    )

    assert "secret" not in report
    assert "db.internal" in report
    assert "Failures: 2." in report
    assert "`x_chartagent.transform.sort[0]` — 2" in report


def test_report_with_no_failures_says_so() -> None:
    report = scan_saved_frames.render_report(
        "postgresql+psycopg://studio:studio@localhost:5432/studio", 0, []
    )

    assert "No failures." in report
