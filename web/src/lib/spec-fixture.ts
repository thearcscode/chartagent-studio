/** Test fixture: a saved frame chart with a fresh cache pointer — the
 * honest Library card. Tests override per case; nothing here is drawn or
 * fetched, it is just the wire shape. */

import type { CacheOut, SpecOut } from "./charts-api";

export const FIXTURE_FRAME: Record<string, unknown> = {
  chart_spec: {
    chartType: "Bar Chart",
    encodings: { x: { field: "b" }, y: { field: "a" } },
  },
};

export const FIXTURE_CACHE: CacheOut = {
  revision_id: "rev-1",
  source_id: "src-1",
  source_kind: "upload",
  row_count: 3,
  elapsed_ms: 41,
  bound_at: "2026-08-29T14:03:45Z",
};

export function makeSpecOut(overrides: Partial<SpecOut> = {}): SpecOut {
  return {
    id: "chart-1",
    title: "Bar chart · q3.csv",
    kind: "frame",
    revision_id: "rev-1",
    revision_number: 1,
    content: FIXTURE_FRAME,
    content_hash: "hash-1",
    authored_flint_version: "0.4.0",
    default_source_id: "src-1",
    created_at: "2026-08-29T00:00:00Z",
    updated_at: "2026-08-29T00:00:00Z",
    cache: FIXTURE_CACHE,
    ...overrides,
  };
}
