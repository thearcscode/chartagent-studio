/** The ticket's component seam, without a browser: a row-count mismatch
 * refuses, names the drop, and leaves the chart area empty — nothing is
 * drawn, no partial render.
 *
 * @vitest-environment jsdom
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BindResponse, SourceOut } from "../lib/charts-api";
import type { FlintGlobal } from "../lib/flint";
import { drawChart } from "../lib/renderers";
import { ChartPage } from "./ChartPage";

vi.mock("@clerk/react", () => ({
  useAuth: () => ({ getToken: async () => "test-token" }),
  UserButton: () => null,
}));

vi.mock("../lib/charts-api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/charts-api")>();
  return {
    ...original,
    listSources: vi.fn(),
    previewBind: vi.fn(),
    savedBind: vi.fn(),
    createSpec: vi.fn(),
    updateSpec: vi.fn(),
    getSpec: vi.fn(),
    uploadSource: vi.fn(),
    registerUrlSource: vi.fn(),
  };
});

vi.mock("../lib/flint", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/flint")>();
  return { ...original, loadFlint: vi.fn() };
});

vi.mock("../lib/renderers", () => ({ drawChart: vi.fn() }));

import { listSources, previewBind } from "../lib/charts-api";
import { loadFlint } from "../lib/flint";

const SOURCE: SourceOut = {
  id: "src-1",
  kind: "upload",
  original_filename: "sales.csv",
  url: null,
  byte_size: 128,
  created_at: "2026-08-29T00:00:00Z",
};

const FRAME = JSON.stringify({
  chart_spec: {
    chartType: "Bar Chart",
    encodings: { x: { field: "b" }, y: { field: "a" } },
  },
});

/** The bind returned three rows… */
function envelope(): BindResponse {
  return {
    flint_version: "0.5.1",
    backend: "echarts",
    input: {
      data: { values: [{ a: 1 }, { a: 2 }, { a: 3 }] },
      chart_spec: {
        chartType: "Bar Chart",
        encodings: { x: { field: "b" }, y: { field: "a" } },
      },
    },
    row_count: 3,
    elapsed: 0.041,
    warnings: [],
    source_schema: {},
  };
}

/** …but the compiled chart holds one point. */
const DISHONEST_FLINT: FlintGlobal = {
  assembleECharts: () => ({ _dataLength: 1 }),
  assembleVegaLite: () => ({}),
  assemblePlotly: () => ({}),
  assembleChartjs: () => ({}),
  assembleExcel: () => ({}),
  isExcelSupported: () => true,
};

describe("ChartPage row-count refusal", () => {
  beforeEach(() => {
    vi.mocked(listSources).mockResolvedValue([SOURCE]);
    vi.mocked(previewBind).mockResolvedValue(envelope());
    vi.mocked(loadFlint).mockResolvedValue(DISHONEST_FLINT);
    vi.mocked(drawChart).mockClear();
  });

  it("refuses, names the drop, and leaves the chart area empty", async () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/charts/new"]}>
        <ChartPage />
      </MemoryRouter>,
    );

    // Wait for sources to load, then pick the source and paste a frame.
    const sourceSelect = await screen.findByLabelText("Data source");
    fireEvent.change(sourceSelect, { target: { value: SOURCE.id } });
    fireEvent.change(screen.getByLabelText(/input frame/i), {
      target: { value: FRAME },
    });
    fireEvent.click(screen.getByRole("button", { name: /bind & draw/i }));

    // Names the drop: rows in, points compiled, rows lost.
    expect(
      await screen.findByText(/3 rows but the compiled echarts chart holds 1 point/i),
    ).toBeTruthy();
    expect(screen.getByText(/2 rows would be silently dropped/i)).toBeTruthy();

    // The chart area is empty — nothing drawn, ever, on a refusal.
    const canvas = container.querySelector(".chart-canvas");
    expect(canvas?.childElementCount).toBe(0);
    expect(drawChart).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(container.querySelector(".chart-area")?.getAttribute("data-state")).toBe(
        "error",
      );
    });
  });
});
