/** Revision-list helpers (#9, #10). `authored_flint_version` is a recorded
 * fact, never a gate (ADR-0007 D11): the UI may name another pin and
 * must not offer to load it. The default diff pair is the latest edit
 * (newest vs the one under it); a single revision diffs against itself.
 */

import type { RevisionOut } from "./charts-api";

/** Copy shown when a revision was saved under a pin other than the one
 * this app serves. `null` when there is nothing to say — including a
 * recipe, which has no authored pin. */
export function pinNote(authored: string | null, served: string): string | null {
  if (authored === null || authored === served) return null;
  return `Saved under Flint ${authored}`;
}

/** Newest-first list: the latest edit is newest vs the row under it.
 * One revision diffs against itself (zero hunks). */
export function defaultDiffPair(revisions: RevisionOut[]): [number, number] | null {
  if (revisions.length === 0) return null;
  if (revisions.length === 1) {
    const only = revisions[0].revision_number;
    return [only, only];
  }
  return [revisions[1].revision_number, revisions[0].revision_number];
}
