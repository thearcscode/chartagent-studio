/** The Library's cache rules (#76; ADR-0007 D6), as pure client logic. A
 * card binds nothing: a pointer that matches the chart's current values
 * reads the cache and compiles in the browser; anything else is *Refresh
 * to bind*. The envelope is reconstructed locally — the served bundle's
 * flint_version (never `authored_flint_version`), the current UI switch's
 * backend, the current revision's frame, the cache's rows.
 */

import type { Backend } from "./backends";
import type { BindResponse, CacheObject, CacheOut, SpecOut } from "./charts-api";

export type PointerState =
  /** The pointer agrees with the chart's current revision and source. */
  | { kind: "fresh"; pointer: CacheOut }
  /** A pointer exists but names another revision or source — *Refresh to
   * bind*. Never a silent bind behind a page load. */
  | { kind: "stale" }
  /** Never bound (or never honestly bound) — *Refresh to bind*. */
  | { kind: "none" };

/** The load rule: compare the pointer's `revision_id` and `source_id` to
 * the chart's current values. */
export function pointerState(card: SpecOut): PointerState {
  const cache = card.cache;
  if (cache === null) return { kind: "none" };
  if (
    cache.revision_id !== card.revision_id ||
    cache.source_id !== card.default_source_id
  ) {
    return { kind: "stale" };
  }
  return { kind: "fresh", pointer: cache };
}

/** The guard key: the slot is overwritten in place, so a `revision_id`
 * disagreement between object and pointer is a wrong chart, not a display
 * that is merely early — discard the object. */
export function cacheObjectMatches(pointer: CacheOut, object: CacheObject): boolean {
  return object.revision_id === pointer.revision_id;
}

function frameSourceSchema(content: Record<string, unknown>): Record<string, string> | null {
  const xc = content.x_chartagent;
  if (typeof xc !== "object" || xc === null) return null;
  const schema = (xc as Record<string, unknown>).source_schema;
  if (typeof schema !== "object" || schema === null) return null;
  return schema as Record<string, string>;
}

/** Reconstruct the envelope a bind would have returned, from local parts:
 * the served bundle's version, the UI switch's backend, the current
 * revision's frame (its `theme_spec` rides along — it is the document's,
 * not an engine setting), the cache's rows. Advisories are not persisted
 * on the cache; they return on the next user-initiated bind. */
export function envelopeFromCache(
  card: SpecOut,
  pointer: CacheOut,
  rows: CacheObject["rows"],
  flintVersion: string,
  backend: Backend,
): BindResponse {
  return {
    flint_version: flintVersion,
    backend,
    input: { ...card.content, data: { values: rows } },
    row_count: pointer.row_count,
    elapsed: pointer.elapsed_ms / 1000,
    warnings: [],
    source_schema: frameSourceSchema(card.content),
  };
}

/** `bound_at` for the card's *as of* line — UTC, minute precision, so the
 * statement is stable wherever the browser sits. */
export function formatBoundAt(boundAt: string): string {
  const date = new Date(boundAt);
  const pad = (value: number) => String(value).padStart(2, "0");
  return (
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ` +
    `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`
  );
}
