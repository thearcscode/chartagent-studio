/** A chart opened straight after the instruction box saved it: when the
 * bind failed after the save, the page says *Refresh to bind* and carries
 * the shared failure message (#49).
 *
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, fetchCacheObject, savedRecipeRefresh, type SpecOut } from "../lib/charts-api";
import { RecipeChartPage } from "./RecipeChartPage";

vi.mock("@clerk/react", () => ({
  useAuth: () => ({ getToken: async () => "test-token" }),
  UserButton: () => null,
}));

vi.mock("../components/SandboxedPaint", () => ({ SandboxedPaint: () => null }));

vi.mock("../lib/charts-api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/charts-api")>();
  return {
    ...original,
    listSources: vi.fn().mockResolvedValue([]),
    fetchShell: vi.fn().mockResolvedValue({ html: "<html></html>" }),
    fetchCacheObject: vi.fn(),
    savedRecipeRefresh: vi.fn(),
  };
});

const SPEC: SpecOut = {
  id: "c1",
  title: "Custom · sales.csv",
  kind: "recipe",
  revision_id: "r1",
  revision_number: 1,
  content: {},
  content_hash: "h",
  authored_flint_version: null,
  default_source_id: "s1",
  created_at: "2026-10-02T00:00:00Z",
  updated_at: "2026-10-02T00:00:00Z",
  cache: null,
};

const BOUND = {
  revision_id: "r1",
  source_id: "s1",
  source_kind: "upload" as const,
  row_count: 3,
  elapsed_ms: 41,
  bound_at: "2026-10-02T12:00:00Z",
};
const FRESH: SpecOut = { ...SPEC, cache: BOUND };

afterEach(cleanup);

function renderOpened(spec: SpecOut, state: object) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: "/charts/c1", state }]}>
      <RecipeChartPage spec={spec} />
    </MemoryRouter>,
  );
}

describe("RecipeChartPage after the instruction box", () => {
  it("shows Refresh to bind with the carried failure message", async () => {
    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: "/charts/c1",
            state: { refreshFailure: { kind: "other", lines: ["bind blew up"] } },
          },
        ]}
      >
        <RecipeChartPage spec={SPEC} />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Refresh to bind")).toBeTruthy();
    expect(screen.getByText("bind blew up")).toBeTruthy();
  });
});

describe("RecipeChartPage as-of line after the instruction box", () => {
  const asOf = () => document.querySelector(".cost-line")?.textContent ?? null;

  it("carries the plan term on arrival", async () => {
    vi.mocked(fetchCacheObject).mockResolvedValue({ revision_id: "r1", rows: [] });
    renderOpened(FRESH, { planElapsedMs: 2340 });
    await waitFor(() => expect(asOf()).toMatch(/^3 rows · 41 ms bind · 2 s plan · as of /));
  });

  it("drops the plan term on the next Refresh", async () => {
    vi.mocked(fetchCacheObject).mockResolvedValue({ revision_id: "r1", rows: [] });
    vi.mocked(savedRecipeRefresh).mockResolvedValue({
      rows: [{ a: 1 }],
      row_count: 1,
      elapsed: 0.02,
      warnings: [],
    });
    renderOpened(FRESH, { planElapsedMs: 2340 });
    await waitFor(() => expect(asOf()).toContain("s plan"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(asOf()).toMatch(/^1 rows · 20 ms · as of /));
    expect(asOf()).not.toContain("plan");
  });

  it("drops the plan term when the Refresh fails, showing the ordinary line", async () => {
    vi.mocked(fetchCacheObject).mockResolvedValue({ revision_id: "r1", rows: [] });
    vi.mocked(savedRecipeRefresh).mockRejectedValue(
      new ApiError(502, { error: "bind_failed", message: "bind blew up" }),
    );
    renderOpened(FRESH, { planElapsedMs: 2340 });
    await waitFor(() => expect(asOf()).toContain("s plan"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("bind blew up")).toBeTruthy();
    expect(asOf()).toMatch(/^3 rows · 41 ms · as of /);
  });

  it("has no as-of line when the first bind failed", async () => {
    renderOpened(SPEC, {
      planElapsedMs: 2340,
      refreshFailure: { kind: "other", lines: ["bind blew up"] },
    });
    expect(await screen.findByText("Refresh to bind")).toBeTruthy();
    expect(asOf()).toBeNull();
  });
});
