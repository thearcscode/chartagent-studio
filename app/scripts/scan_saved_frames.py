"""One-off scan: validate every saved frame against the new chartagent.

chartagent-studio#26. Settled in thearcscode/chartagent#139 — ADR-0023
Decision 5: after the library types `x_chartagent.transform` (#147), a
stored frame with a data-free shape fault (for example a sort item written
as ``{field, order}`` instead of the now-typed ``{field, dir}``) fails when
it is *parsed*, not only when it is bound. This scan finds those frames
before Studio moves to a chartagent version past #147, so a human can decide
what happens to them ahead of the upgrade.

Read-only: every row is a SELECT. Nothing is written, migrated, or re-saved
(chartagent ADR-0010 D1) — that is a separate, later decision.

Run once per deployed environment that might hold ``spec_revisions`` rows,
pointing ``--database-url`` (or ``DATABASE_URL``) at each in turn:

    uv run --no-sync python scripts/scan_saved_frames.py
    uv run --no-sync python scripts/scan_saved_frames.py \
        --database-url postgresql+psycopg://... --out report-prod.json

The chartagent import must resolve the *new* library (the one containing
#147) — dev's `[tool.uv.sources]` editable path already does this, so no
separate environment is needed there; point `--database-url` at a real
environment while keeping that resolution. Only `chartagent.InputFrame` is
used — the library's public API.

Out of scope (chartagent-studio#26): recipes (``kind = 'recipe'``) — nothing
saves those yet.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit, urlunsplit

from chartagent import InputFrame
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from studio.models import SpecRevision


@dataclass(frozen=True)
class Failure:
    chart_id: str
    revision_number: int
    exception_type: str
    message: str
    # The field path the message names, when it names one (for example
    # "x_chartagent.transform.sort[0]") — the group key for the report.
    # Falls back to the exception type when the message carries no path.
    path: str


def _redact(database_url: str) -> str:
    """Host and db name only — never the credentials in the report."""
    parts = urlsplit(database_url)
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _path_for(message: str, exception_type: str) -> str:
    # chartagent's SpecShapeError formats x_chartagent.transform failures as
    # "<field path>: <msg>" (chartagent/frame/input.py:_map_validation_error).
    # Other shape/vocabulary errors carry no such path; group those by type.
    head, sep, _ = message.partition(": ")
    if sep and " " not in head:
        return head
    return exception_type


def scan(session: Session) -> tuple[int, list[Failure]]:
    """Validate every saved frame. Returns (rows scanned, failures)."""
    rows = session.execute(
        select(SpecRevision).where(SpecRevision.kind == "frame")
    ).scalars()

    scanned = 0
    failures: list[Failure] = []
    for revision in rows:
        scanned += 1
        try:
            InputFrame.model_validate(revision.content)
        except Exception as exc:  # noqa: BLE001 - recording every failure, by design
            message = str(exc)
            exception_type = type(exc).__name__
            failures.append(
                Failure(
                    chart_id=str(revision.chart_id),
                    revision_number=revision.revision_number,
                    exception_type=exception_type,
                    message=message,
                    path=_path_for(message, exception_type),
                )
            )
    return scanned, failures


def render_report(database_url: str, scanned: int, failures: list[Failure]) -> str:
    lines = [
        f"# Saved frame scan — {_redact(database_url)}",
        "",
        f"Scanned {scanned} `spec_revisions` row(s) with `kind = 'frame'`.",
        f"Failures: {len(failures)}.",
        "",
    ]
    if not failures:
        lines.append("No failures. Every saved frame parses under the new library.")
        return "\n".join(lines) + "\n"

    grouped: dict[str, list[Failure]] = defaultdict(list)
    for failure in failures:
        grouped[failure.path].append(failure)

    lines.append("## By field path")
    lines.append("")
    for path, group in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"### `{path}` — {len(group)}")
        lines.append("")
        for failure in group:
            lines.append(
                f"- chart `{failure.chart_id}` revision {failure.revision_number} "
                f"({failure.exception_type}): {failure.message}"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--database-url",
        default=None,
        help="Defaults to $DATABASE_URL, then the compose dev database.",
    )
    parser.add_argument(
        "--out",
        type=argparse.FileType("w"),
        default=None,
        help="Write the full report (Markdown) here in addition to stdout.",
    )
    parser.add_argument(
        "--json-out",
        type=argparse.FileType("w"),
        default=None,
        help="Write the raw failure list as JSON here (for tooling, not humans).",
    )
    args = parser.parse_args(argv)

    database_url = (
        args.database_url
        or os.environ.get("DATABASE_URL")
        or "postgresql+psycopg://studio:studio@localhost:5432/studio"
    )

    engine = create_engine(database_url)
    with Session(engine) as session:
        scanned, failures = scan(session)
        session.rollback()  # belt and suspenders: this session never wrote.

    report = render_report(database_url, scanned, failures)
    print(report)
    if args.out is not None:
        args.out.write(report)
    if args.json_out is not None:
        json.dump([asdict(f) for f in failures], args.json_out, indent=2)
        args.json_out.write("\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
