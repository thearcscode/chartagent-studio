/** A chart's revision history (#9). Current is whatever the server
 * marked from the pointer — after a revert the highest number is not
 * current, and this list must not recompute it. The authored pin is
 * displayed and never offered as a bundle to load.
 */

import type { RevisionOut } from "../lib/charts-api";
import { formatBoundAt } from "../lib/library";
import { pinNote } from "../lib/revisions";

export function RevisionList({
  revisions,
  servedFlintVersion,
  onRevert,
  reverting = false,
}: {
  revisions: RevisionOut[];
  servedFlintVersion: string;
  onRevert: (revisionNumber: number) => void;
  reverting?: boolean;
}) {
  return (
    <ol className="revision-list">
      {revisions.map((row) => {
        const note = pinNote(row.authored_flint_version, servedFlintVersion);
        return (
          <li key={row.revision_number} className="revision-row">
            <div className="revision-row-main">
              <span className="revision-row-id">rev {row.revision_number}</span>
              {row.current ? (
                <span className="revision-chip">current</span>
              ) : null}
              <time className="revision-row-time" dateTime={row.created_at}>
                {formatBoundAt(row.created_at)}
              </time>
            </div>
            <div className="revision-row-meta">
              {row.authored_flint_version ? (
                <span className="revision-row-pin">
                  Flint {row.authored_flint_version}
                </span>
              ) : null}
              {note ? <span className="revision-row-note">{note}</span> : null}
            </div>
            {row.current ? null : (
              <button
                type="button"
                className="ghost-button"
                disabled={reverting}
                onClick={() => onRevert(row.revision_number)}
              >
                Revert to revision {row.revision_number}
              </button>
            )}
          </li>
        );
      })}
    </ol>
  );
}
