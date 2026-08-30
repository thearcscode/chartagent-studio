/** Shared hunk list for the #10 revision diff and the #11 remap patch. */

import type { DiffHunk } from "../lib/charts-api";

function formatValue(value: unknown): string {
  return JSON.stringify(value);
}

export function HunkList({ hunks }: { hunks: DiffHunk[] }) {
  return (
    <ol className="revision-diff-hunks">
      {hunks.map((hunk) => (
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
  );
}
