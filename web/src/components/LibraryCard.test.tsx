/** The Library card's rules, without a browser: a fresh pointer reads the
 * cache object and draws; a stale pointer, a missing object, or a
 * guard-key mismatch is *Refresh to bind* — and none of them binds. A
 * backend switch recompiles the same rows without re-fetching. A
 * URL-backed card states its *as of*.
 *
 * @vitest-environment jsdom
 */

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CacheObject, SpecOut } from "../lib/charts-api";
import type { FlintGlobal } from "../lib/flint";
import { drawChart } from "../lib/renderers";
import { FIXTURE_CACHE, makeSpecOut as card } from "../lib/spec-fixture";
import { LibraryCard } from "./LibraryCard";

// A stable getToken — Clerk's own is memoised; a per-render arrow here
// would re-run the card's effects forever.
const GET_TOKEN = async () => "test-token";

vi.mock("@clerk/react", () => ({
  useAuth: () => ({ getToken: GET_TOKEN }),
  UserButton: () => null,
}));

vi.mock("../lib/charts-api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/charts-api")>();
  return { ...original, fetchCacheObject: vi.fn() };
});

vi.mock("../lib/renderers", () => ({ drawChart: vi.fn() }));

import { fetchCacheObject } from "../lib/charts-api";

afterEach(cleanup);

const CACHE_OBJECT: CacheObject = {
  revision_id: "rev-1",
  rows: [
    { a: 1, b: "x" },
    { a: 2, b: "y" },
    { a: 3, b: "z" },
  ],
};

function rowCountOf(input: unknown): number {
  return (input as { data: { values: unknown[] } }).data.values.length;
}

/** Compiles one point per cached row, on every backend. */
const HONEST_FLINT: FlintGlobal = {
  assembleECharts: (input) => ({ _dataLength: rowCountOf(input) }),
  assembleVegaLite: (input) => ({ _dataLength: rowCountOf(input) }),
  assemblePlotly: (input) => ({ _dataLength: rowCountOf(input) }),
  assembleChartjs: (input) => ({ _dataLength: rowCountOf(input) }),
  assembleExcel: (input) => ({ _dataLength: rowCountOf(input) }),
  isExcelSupported: () => true,
};

function renderCard(spec: SpecOut, backend: "echarts" | "plotly" | "excel" = "echarts") {
  return render(
    <MemoryRouter>
      <LibraryCard card={spec} backend={backend} flint={HONEST_FLINT} />
    </MemoryRouter>,
  );
}

describe("LibraryCard", () => {
  beforeEach(() => {
    // No setup file resets anything — clear accumulated calls explicitly.
    vi.clearAllMocks();
    vi.mocked(fetchCacheObject).mockResolvedValue(CACHE_OBJECT);
    vi.mocked(drawChart).mockResolvedValue(() => {});
  });

  it("reads the cache and draws — no bind, and the cost line is the bind's", async () => {
    renderCard(card());

    await waitFor(() => {
      expect(vi.mocked(drawChart)).toHaveBeenCalledTimes(1);
    });
    expect(vi.mocked(fetchCacheObject)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetchCacheObject).mock.calls[0][1]).toBe("chart-1");
    // The backend the assembler saw is the UI switch's, and the rows are
    // the cache's.
    expect(vi.mocked(drawChart).mock.calls[0][1]).toBe("echarts");
    expect(await screen.findByText("3 rows · 41 ms · ECharts")).toBeTruthy();
    // The title links to the chart page.
    const title = screen.getByRole("link", { name: "Bar chart · q3.csv" });
    expect(title.getAttribute("href")).toBe("/charts/chart-1");
  });

  it("says Refresh to bind on a stale pointer — and never fetches, never binds", async () => {
    renderCard(card({ revision_id: "rev-2", revision_number: 2 }));

    const link = await screen.findByRole("link", { name: "Refresh to bind" });
    expect(link.getAttribute("href")).toBe("/charts/chart-1");
    expect(screen.getByText(/cache predates this revision/)).toBeTruthy();
    expect(vi.mocked(fetchCacheObject)).not.toHaveBeenCalled();
    expect(vi.mocked(drawChart)).not.toHaveBeenCalled();
  });

  it("says Refresh to bind when the chart was never bound", async () => {
    renderCard(card({ cache: null }));

    expect(await screen.findByRole("link", { name: "Refresh to bind" })).toBeTruthy();
    expect(screen.getByText("Never bound.")).toBeTruthy();
    expect(vi.mocked(fetchCacheObject)).not.toHaveBeenCalled();
  });

  it("discards an object whose guard key disagrees with the pointer", async () => {
    vi.mocked(fetchCacheObject).mockResolvedValue({
      revision_id: "rev-elsewhere",
      rows: CACHE_OBJECT.rows,
    });
    renderCard(card());

    expect(await screen.findByRole("link", { name: "Refresh to bind" })).toBeTruthy();
    // Named as what it is: a wrong chart, not a display that is merely early.
    expect(screen.getByText(/names another revision/)).toBeTruthy();
    expect(vi.mocked(drawChart)).not.toHaveBeenCalled();
  });

  it("says Refresh to bind when the object is missing", async () => {
    vi.mocked(fetchCacheObject).mockResolvedValue(null);
    renderCard(card());

    expect(await screen.findByRole("link", { name: "Refresh to bind" })).toBeTruthy();
    expect(screen.getByText("The cached object is gone.")).toBeTruthy();
    expect(vi.mocked(drawChart)).not.toHaveBeenCalled();
  });

  it("states as-of on a URL-backed cache", async () => {
    renderCard(card({ cache: { ...FIXTURE_CACHE, source_kind: "url" } }));

    expect(
      await screen.findByText("3 rows · 41 ms · ECharts · as of 2026-08-29 14:03 UTC"),
    ).toBeTruthy();
  });

  it("recompiles the same rows on a backend switch — no refetch, no bind", async () => {
    const spec = card();
    const { rerender } = renderCard(spec);
    await waitFor(() => {
      expect(vi.mocked(drawChart)).toHaveBeenCalledTimes(1);
    });

    rerender(
      <MemoryRouter>
        <LibraryCard card={spec} backend="plotly" flint={HONEST_FLINT} />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(vi.mocked(drawChart)).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(drawChart).mock.calls[1][1]).toBe("plotly");
    expect(await screen.findByText("3 rows · 41 ms · Plotly")).toBeTruthy();
    // The rows were not re-fetched: the cache read happened once.
    expect(vi.mocked(fetchCacheObject)).toHaveBeenCalledTimes(1);
  });

  it("shows the amber gate for a frame Excel cannot draw", async () => {
    const gatedFlint: FlintGlobal = { ...HONEST_FLINT, isExcelSupported: () => false };
    render(
      <MemoryRouter>
        <LibraryCard card={card()} backend="excel" flint={gatedFlint} />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/not one of the chart types Excel draws/)).toBeTruthy();
    expect(vi.mocked(drawChart)).not.toHaveBeenCalled();
  });
});
