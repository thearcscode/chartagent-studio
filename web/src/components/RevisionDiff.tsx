/** Structural hunks from the server-side canonical_json diff (#10). The
 * user picks any two revisions; this panel renders the paths. A
 * source-schema-only change is labelled — it is the ordinary shape of a
 * chart's first honest save, not an edit anybody made.
 */

import type { DiffOut, RevisionOut } from "../lib/charts-api";

function formatValue(value: unknown): string {
  return JSON.stringify(value);
}

export function RevisionDiff({
  revisions,
  fromRevision,
  toRevision,
  diff,
  onCompare,
}: {
  revisions: RevisionOut[];
  fromRevision: number;
  toRevision: number;
  diff: DiffOut | null;
  onCompare: (from: number, to: number) => void;
}) {
  return (
    <div className="revision-diff">
      <div className="revision-diff-head">
        <span className="revision-diff-title">spec.diff</span>
        {diff ? (
          <span className="revision-diff-count">
            {diff.hunks.length} {diff.hunks.length === 1 ? "hunk" : "hunks"}
          </span>
        ) : null}
      </div>
      <div className="revision-diff-picks">
        <label>
          From
          <select
            aria-label="Diff from revision"
            value={fromRevision}
            onChange={(event) => onCompare(Number(event.target.value), toRevision)}
          >
            {revisions.map((row) => (
              <option key={`from-${row.revision_number}`} value={row.revision_number}>
                rev {row.revision_number}
              </option>
            ))}
          </select>
        </label>
        <label>
          To
          <select
            aria-label="Diff to revision"
            value={toRevision}
            onChange={(event) => onCompare(fromRevision, Number(event.target.value))}
          >
            {revisions.map((row) => (
              <option key={`to-${row.revision_number}`} value={row.revision_number}>
                rev {row.revision_number}
              </option>
            ))}
          </select>
        </label>
      </div>
      {diff?.source_schema_only ? (
        <p className="revision-diff-label">source-schema-only change</p>
      ) : null}
      {diff && diff.hunks.length === 0 ? (
        <p className="revision-diff-empty">Identical revisions — zero hunks.</p>
      ) : null}
      {diff ? (
        <ol className="revision-diff-hunks">
          {diff.hunks.map((hunk) => (
            <li key={`${hunk.op}:${hunk.path}`}>
              <span className="revision-diff-path">{hunk.path}</span>
              {hunk.op === "added" ? (
                <span className="revision-diff-to">+ {formatValue(hunk.to_value)}</span>
              ) : null}
              {hunk.op === "removed" ? (
                <span className="revision-diff-from">− {formatValue(hunk.from_value)}</span>
              ) : null}
              {hunk.op === "changed" ? (
                <>
                  <span className="revision-diff-from">− {formatValue(hunk.from_value)}</span>
                  <span className="revision-diff-to">+ {formatValue(hunk.to_value)}</span>
                </>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}
