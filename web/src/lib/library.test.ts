/** The Library's cache rules, without a browser: the pointer match that
 * decides between a cached compile and *Refresh to bind*, the guard key
 * that discards a wrong-chart object, and the local envelope
 * reconstruction — served flint_version, the UI switch's backend, the
 * current frame (theme_spec intact), the cache's rows, no advisories.
 */

import { describe, expect, it } from "vitest";

import {
  cacheObjectMatches,
  envelopeFromCache,
  formatBoundAt,
  pointerState,
} from "./library";
import { FIXTURE_CACHE as POINTER, makeSpecOut as card } from "./spec-fixture";

describe("pointerState", () => {
  it("is fresh when the pointer names the current revision and source", () => {
    const state = pointerState(card());
    expect(state).toEqual({ kind: "fresh", pointer: POINTER });
  });

  it("is none when the chart was never bound", () => {
    expect(pointerState(card({ cache: null }))).toEqual({ kind: "none" });
  });

  it("is stale when the pointer names an older revision", () => {
    expect(pointerState(card({ revision_id: "rev-2" }))).toEqual({ kind: "stale" });
  });

  it("is stale when the pointer names another source", () => {
    expect(pointerState(card({ default_source_id: "src-2" }))).toEqual({
      kind: "stale",
    });
  });
});

describe("cacheObjectMatches", () => {
  it("keeps the object when the guard key agrees with the pointer", () => {
    expect(
      cacheObjectMatches(POINTER, { revision_id: "rev-1", rows: [{ a: 1 }] }),
    ).toBe(true);
  });

  it("discards the object when the guard key disagrees — a wrong chart, not an early one", () => {
    expect(
      cacheObjectMatches(POINTER, { revision_id: "rev-2", rows: [{ a: 1 }] }),
    ).toBe(false);
  });
});

describe("envelopeFromCache", () => {
  const rows = [
    { a: 1, b: "x" },
    { a: 2, b: "y" },
  ];

  it("reconstructs the envelope from local parts", () => {
    const envelope = envelopeFromCache(card(), POINTER, rows, "0.5.1", "plotly");
    // flint_version is the served bundle's — never authored_flint_version.
    expect(envelope.flint_version).toBe("0.5.1");
    // backend is the current UI switch's, not a stored one.
    expect(envelope.backend).toBe("plotly");
    // The frame comes from the current revision, the rows from the cache.
    expect(envelope.input.chart_spec).toEqual(card().content.chart_spec);
    expect(envelope.input.data).toEqual({ values: rows });
    // The cost line is the bind that produced the picture.
    expect(envelope.row_count).toBe(3);
    expect(envelope.elapsed).toBeCloseTo(0.041);
    // Advisories are not persisted on the cache.
    expect(envelope.warnings).toEqual([]);
  });

  it("keeps theme_spec on the frame and carries the recorded source_schema", () => {
    const withTheme = card({
      content: {
        chart_spec: {
          chartType: "Bar Chart",
          encodings: { x: { field: "b" }, y: { field: "a" } },
        },
        theme_spec: { palette: ["#123456"] },
        x_chartagent: { spec_version: "1.1", source_schema: { a: "number" } },
      },
    });
    const envelope = envelopeFromCache(withTheme, POINTER, rows, "0.5.1", "echarts");
    expect(envelope.input.theme_spec).toEqual({ palette: ["#123456"] });
    expect(envelope.source_schema).toEqual({ a: "number" });
  });

  it("reports no source_schema for a frame that predates the key", () => {
    const envelope = envelopeFromCache(card(), POINTER, rows, "0.5.1", "echarts");
    expect(envelope.source_schema).toBeNull();
  });
});

describe("formatBoundAt", () => {
  it("states the bound time in UTC at minute precision", () => {
    expect(formatBoundAt("2026-08-29T14:03:45Z")).toBe("2026-08-29 14:03 UTC");
  });
});
