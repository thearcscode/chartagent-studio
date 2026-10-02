/** A chart opened straight after the instruction box saved it: when the
 * bind failed after the save, the page says *Refresh to bind* and carries
 * the shared failure message (#49).
 *
 * @vitest-environment jsdom
 */

import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SpecOut } from "../lib/charts-api";
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

afterEach(cleanup);

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
