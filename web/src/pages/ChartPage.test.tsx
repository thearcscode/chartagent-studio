/** The ticket's component seam, without a browser: a row-count mismatch
 * refuses, names the drop, and leaves the chart area empty — nothing is
 * drawn, no partial render.
 *
 * @vitest-environment jsdom
 */

import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type BindResponse, type SourceOut, type SpecOut } from "../lib/charts-api";
import type { FlintGlobal } from "../lib/flint";
import { drawChart } from "../lib/renderers";
import { ChartPage } from "./ChartPage";

const { getToken } = vi.hoisted(() => ({
  getToken: async () => "test-token",
}));

vi.mock("@clerk/react", () => ({
  useAuth: () => ({ getToken }),
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
    deleteSpec: vi.fn(),
    deleteSource: vi.fn(),
    downloadWorkbook: vi.fn(),
    listRevisions: vi.fn(),
    revertSpec: vi.fn(),
    diffRevisions: vi.fn(),
  };
});

vi.mock("../lib/flint", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/flint")>();
  return { ...original, loadFlint: vi.fn() };
});

vi.mock("../lib/renderers", () => ({ drawChart: vi.fn() }));

import { diffRevisions, getSpec, listRevisions, listSources, previewBind, revertSpec, savedBind } from "../lib/charts-api";
import { loadFlint } from "../lib/flint";

afterEach(cleanup);

const SOURCE: SourceOut = {
  id: "src-1",
  kind: "upload",
  original_filename: "sales.csv",
  url: null,
  byte_size: 128,
  // The source the failed refresh is pointed at — `a` is gone, `c` is new.
  schema_snapshot: {
    columns: [
      { name: "c", type: "BIGINT" },
      { name: "b", type: "VARCHAR" },
    ],
  },
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
  generateOfficeJs: () => ({ code: "async function renderFlintChart() {}" }),
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

/** An envelope whose row count agrees with its rows, so the honesty guard
 * passes and the chart draws. */
function honestEnvelope(rows: number): BindResponse {
  return {
    flint_version: "0.5.1",
    backend: "echarts",
    input: {
      data: {
        values: Array.from({ length: rows }, (_, index) => ({
          a: index + 1,
          b: `v${index + 1}`,
        })),
      },
      chart_spec: {
        chartType: "Bar Chart",
        encodings: { x: { field: "b" }, y: { field: "a" } },
      },
    },
    row_count: rows,
    elapsed: 0.041,
    warnings: [],
    source_schema: {},
  };
}

/** Compiles exactly as many points as the envelope carries — the honest
 * counterpart of DISHONEST_FLINT above. */
const HONEST_FLINT: FlintGlobal = {
  assembleECharts: (input) => ({
    _dataLength: (input as { data: { values: unknown[] } }).data.values.length,
    series: [{ type: "bar" }],
  }),
  assembleVegaLite: () => ({}),
  assemblePlotly: () => ({}),
  assembleChartjs: () => ({}),
  assembleExcel: () => ({}),
  isExcelSupported: () => true,
  generateOfficeJs: () => ({ code: "async function renderFlintChart() {}" }),
};

const SAVED_SPEC: SpecOut = {
  id: "chart-1",
  title: "Bar chart · sales.csv",
  kind: "frame",
  revision_id: "rev-1",
  revision_number: 1,
  content: {
    chart_spec: {
      chartType: "Bar Chart",
      encodings: { x: { field: "b" }, y: { field: "a" } },
    },
  },
  content_hash: "hash-1",
  authored_flint_version: "0.5.1",
  default_source_id: SOURCE.id,
  created_at: "2026-08-29T00:00:00Z",
  updated_at: "2026-08-29T00:00:00Z",
  cache: {
    revision_id: "rev-1",
    source_id: SOURCE.id,
    source_kind: "upload",
    row_count: 3,
    elapsed_ms: 41,
    bound_at: "2026-08-29T00:00:00Z",
  },
};

function renderSavedChart() {
  return render(
    <MemoryRouter initialEntries={[`/charts/${SAVED_SPEC.id}`]}>
      <Routes>
        <Route path="/charts/:chartId" element={<ChartPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ChartPage open a saved chart", () => {
  beforeEach(() => {
    vi.mocked(listSources).mockResolvedValue([SOURCE]);
    vi.mocked(getSpec).mockResolvedValue(SAVED_SPEC);
    vi.mocked(loadFlint).mockResolvedValue(HONEST_FLINT);
    vi.mocked(savedBind).mockResolvedValue(honestEnvelope(3));
    vi.mocked(drawChart).mockClear();
  });

  it("loads the saved spec after Strict Mode remounts the open effect", async () => {
    render(
      <StrictMode>
        <MemoryRouter initialEntries={[`/charts/${SAVED_SPEC.id}`]}>
          <Routes>
            <Route path="/charts/:chartId" element={<ChartPage />} />
          </Routes>
        </MemoryRouter>
      </StrictMode>,
    );

    await waitFor(() => {
      const title = screen.getByLabelText("Chart title") as HTMLInputElement;
      expect(title.value).toBe("Bar chart · sales.csv");
    });
    expect(await screen.findByRole("button", { name: "Refresh" })).toBeTruthy();
    expect(await screen.findByText("3 rows · 41 ms · ECharts")).toBeTruthy();
  });
});

describe("ChartPage refresh", () => {
  beforeEach(() => {
    vi.mocked(listSources).mockResolvedValue([SOURCE]);
    vi.mocked(getSpec).mockResolvedValue(SAVED_SPEC);
    vi.mocked(loadFlint).mockResolvedValue(HONEST_FLINT);
    vi.mocked(savedBind).mockResolvedValue(honestEnvelope(3));
    vi.mocked(drawChart).mockClear();
  });

  it("redraws from the new envelope on a successful refresh", async () => {
    renderSavedChart();
    // The user-initiated open bind draws the saved chart first.
    expect(await screen.findByText("3 rows · 41 ms · ECharts")).toBeTruthy();
    await waitFor(() => {
      expect(document.querySelector(".chart-area")?.getAttribute("data-series-count")).toBe("1");
    });

    vi.mocked(savedBind).mockResolvedValueOnce(honestEnvelope(2));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText("2 rows · 41 ms · ECharts")).toBeTruthy();
    // The refresh is one bind against the chart's source, trigger refresh.
    expect(vi.mocked(savedBind).mock.calls.at(-1)?.[2]).toEqual({
      backend: "echarts",
      source_id: undefined,
      trigger: "refresh",
    });
    // The picture redrew from the new envelope — same client path as a draw.
    await waitFor(() => {
      expect(vi.mocked(drawChart).mock.calls.length).toBe(2);
    });
  });

  it("keeps the previous picture and renders the three-column table on a failed refresh", async () => {
    const { container } = renderSavedChart();
    expect(await screen.findByText("3 rows · 41 ms · ECharts")).toBeTruthy();
    const drawsBefore = vi.mocked(drawChart).mock.calls.length;

    vi.mocked(savedBind).mockRejectedValueOnce(
      new ApiError(409, {
        error: "schema_drift",
        message: "source column(s) dropped: a",
        stage: "source",
        drifted: [{ name: "a", kind: "dropped", expected: "a", found: null }],
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText("SchemaDriftError")).toBeTruthy();
    expect(screen.getByText("Nothing was rendered and no model was called.")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: /spec references/i })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: /snapshot has/i })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: /status/i })).toBeTruthy();
    expect(screen.getByText("dropped")).toBeTruthy();
    expect(screen.getByText("added · ignored")).toBeTruthy();
    expect(screen.getByText("c, b")).toBeTruthy();
    // A drop plus an extra snapshot column is not a rename.
    expect(screen.queryByText("renamed")).toBeNull();
    expect(screen.queryByRole("button", { name: /regenerate/i })).toBeNull();
    expect(screen.queryByText(/schedule/i)).toBeNull();
    expect(screen.queryByText(/light mode/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /remap/i })).toBeNull();

    // The previous picture is untouched: no redraw, no emptied area,
    // the cost line still describes the bind that produced the picture.
    expect(vi.mocked(drawChart).mock.calls.length).toBe(drawsBefore);
    expect(container.querySelector(".chart-area")?.getAttribute("data-state")).toBe(
      "rendered",
    );
    expect(screen.getByText("3 rows · 41 ms · ECharts")).toBeTruthy();
  });

  it("names a retype as a retype and does not offer a remap", async () => {
    renderSavedChart();
    expect(await screen.findByText("3 rows · 41 ms · ECharts")).toBeTruthy();

    vi.mocked(savedBind).mockRejectedValueOnce(
      new ApiError(409, {
        error: "schema_drift",
        message: "bucket `number` → `string` (DuckDB VARCHAR) on a",
        stage: "source",
        drifted: [{ name: "a", kind: "retyped", expected: "number", found: "string" }],
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText("retyped")).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: /remap|column/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /remap/i })).toBeNull();
  });

  it("leaves the chart exactly as it was when the recovery screen is abandoned", async () => {
    const { container } = renderSavedChart();
    expect(await screen.findByText("3 rows · 41 ms · ECharts")).toBeTruthy();
    const drawsBefore = vi.mocked(drawChart).mock.calls.length;

    vi.mocked(savedBind).mockRejectedValueOnce(
      new ApiError(409, {
        error: "schema_drift",
        message: "source column(s) dropped: a",
        stage: "source",
        drifted: [{ name: "a", kind: "dropped", expected: "a", found: null }],
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("SchemaDriftError")).toBeTruthy();

    const bindsBeforeDismiss = vi.mocked(savedBind).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Leave as is" }));

    expect(screen.queryByText("SchemaDriftError")).toBeNull();
    expect(vi.mocked(savedBind).mock.calls.length).toBe(bindsBeforeDismiss);
    expect(vi.mocked(drawChart).mock.calls.length).toBe(drawsBefore);
    expect(container.querySelector(".chart-area")?.getAttribute("data-state")).toBe(
      "rendered",
    );
    expect(screen.getByText("3 rows · 41 ms · ECharts")).toBeTruthy();
  });
});

describe("ChartPage retype_unchecked", () => {
  beforeEach(() => {
    vi.mocked(listSources).mockResolvedValue([SOURCE]);
    vi.mocked(getSpec).mockResolvedValue(SAVED_SPEC);
    vi.mocked(loadFlint).mockResolvedValue(HONEST_FLINT);
    vi.mocked(drawChart).mockClear();
  });

  it("draws a chart with no baseline and names the partial check as actionable", async () => {
    vi.mocked(savedBind).mockResolvedValue({
      ...honestEnvelope(3),
      warnings: [
        {
          code: "retype_unchecked",
          message: "source_schema baseline is absent; columns unchecked: a",
        },
      ],
    });
    const { container } = renderSavedChart();

    expect(await screen.findByText("3 rows · 41 ms · ECharts")).toBeTruthy();
    expect(container.querySelector(".chart-area")?.getAttribute("data-state")).toBe(
      "rendered",
    );
    expect(screen.getByText("retype_unchecked")).toBeTruthy();
    expect(screen.getByText(/source_schema baseline is absent/i)).toBeTruthy();
    expect(
      screen.getByText(/The retype check is running partially. One save records the source schema baseline./),
    ).toBeTruthy();
  });
});

const EXCEL_FLINT: FlintGlobal = {
  ...HONEST_FLINT,
  assembleExcel: (input) => {
    const values = (input as { data: { values: unknown[] } }).data.values;
    return {
      schema: "flint.excel.chart/v1",
      data: [["b", "a"], ...values.map(() => ["x", 1])],
    };
  },
  generateOfficeJs: () => ({ code: "async function renderFlintChart() {}" }),
};

describe("ChartPage Excel download", () => {
  beforeEach(() => {
    vi.mocked(listSources).mockResolvedValue([SOURCE]);
    vi.mocked(loadFlint).mockResolvedValue(EXCEL_FLINT);
    vi.mocked(drawChart).mockClear();
  });

  it("offers an .xlsx when Excel compiles with rows", async () => {
    vi.mocked(previewBind).mockResolvedValue(honestEnvelope(3));
    render(
      <MemoryRouter initialEntries={["/charts/new"]}>
        <ChartPage />
      </MemoryRouter>,
    );
    fireEvent.change(await screen.findByLabelText("Data source"), {
      target: { value: SOURCE.id },
    });
    fireEvent.change(screen.getByLabelText(/input frame/i), {
      target: { value: FRAME },
    });
    fireEvent.click(screen.getByRole("button", { name: /bind & draw/i }));
    expect(await screen.findByText("3 rows · 41 ms · ECharts")).toBeTruthy();

    vi.mocked(previewBind).mockResolvedValue({
      ...honestEnvelope(3),
      backend: "excel",
    });
    fireEvent.click(screen.getByRole("button", { name: "Excel" }));

    expect(await screen.findByText(/Excel draws in Excel, not in the browser/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Download .xlsx" })).toBeTruthy();
    expect(drawChart).toHaveBeenCalled();
  });

  it("does not offer a workbook on zero rows", async () => {
    vi.mocked(previewBind).mockResolvedValue(honestEnvelope(3));
    render(
      <MemoryRouter initialEntries={["/charts/new"]}>
        <ChartPage />
      </MemoryRouter>,
    );
    fireEvent.change(await screen.findByLabelText("Data source"), {
      target: { value: SOURCE.id },
    });
    fireEvent.change(screen.getByLabelText(/input frame/i), {
      target: { value: FRAME },
    });
    fireEvent.click(screen.getByRole("button", { name: /bind & draw/i }));
    expect(await screen.findByText("3 rows · 41 ms · ECharts")).toBeTruthy();

    vi.mocked(previewBind).mockResolvedValue({
      ...honestEnvelope(0),
      backend: "excel",
    });
    fireEvent.click(screen.getByRole("button", { name: "Excel" }));

    expect(await screen.findByText(/Excel refuses on zero rows/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Download .xlsx" })).toBeNull();
  });
});

const SAVED_SPEC_REV2: SpecOut = {
  ...SAVED_SPEC,
  revision_id: "rev-2",
  revision_number: 2,
  content: {
    chart_spec: {
      chartType: "Bar Chart",
      encodings: { x: { field: "a" }, y: { field: "a" } },
    },
  },
  content_hash: "hash-2",
  cache: {
    revision_id: "rev-2",
    source_id: SOURCE.id,
    source_kind: "upload",
    row_count: 3,
    elapsed_ms: 41,
    bound_at: "2026-08-29T00:00:00Z",
  },
};

const REVERTED_TO_REV1: SpecOut = {
  ...SAVED_SPEC,
  cache: SAVED_SPEC_REV2.cache,
};

describe("ChartPage revert", () => {
  beforeEach(() => {
    vi.mocked(listSources).mockResolvedValue([SOURCE]);
    vi.mocked(getSpec).mockResolvedValue(SAVED_SPEC_REV2);
    vi.mocked(loadFlint).mockResolvedValue(HONEST_FLINT);
    vi.mocked(savedBind).mockResolvedValue(honestEnvelope(3));
    vi.mocked(listRevisions).mockResolvedValue([
      {
        revision_number: 2,
        created_at: "2026-08-30T12:02:00Z",
        content_hash: "hash-2",
        authored_flint_version: "0.5.1",
        current: true,
      },
      {
        revision_number: 1,
        created_at: "2026-08-30T12:01:00Z",
        content_hash: "hash-1",
        authored_flint_version: "0.5.1",
        current: false,
      },
    ]);
    vi.mocked(revertSpec).mockResolvedValue(REVERTED_TO_REV1);
    vi.mocked(diffRevisions).mockResolvedValue({
      from_revision: 1,
      to_revision: 2,
      source_schema_only: false,
      hunks: [
        {
          op: "changed",
          path: "/chart_spec/encodings/x/field",
          from_value: "b",
          to_value: "a",
        },
      ],
    });
    vi.mocked(drawChart).mockClear();
  });

  it("repoints, empties the picture, and says Refresh to bind without binding", async () => {
    const { container } = render(
      <MemoryRouter initialEntries={[`/charts/${SAVED_SPEC_REV2.id}`]}>
        <Routes>
          <Route path="/charts/:chartId" element={<ChartPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("3 rows · 41 ms · ECharts")).toBeTruthy();
    await waitFor(() => {
      expect(container.querySelector(".chart-area")?.getAttribute("data-state")).toBe(
        "rendered",
      );
    });
    const bindsBefore = vi.mocked(savedBind).mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "History" }));
    expect(await screen.findByRole("button", { name: "Revert to revision 1" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Revert to revision 1" }));

    expect(await screen.findByText("Refresh to bind")).toBeTruthy();
    expect(container.querySelector(".chart-area")?.getAttribute("data-state")).toBe(
      "stale",
    );
    expect(container.querySelector(".chart-toolbar .revision-chip")?.textContent).toBe(
      "rev 1",
    );
    expect(vi.mocked(savedBind).mock.calls.length).toBe(bindsBefore);
    expect(vi.mocked(revertSpec)).toHaveBeenCalledWith(getToken, SAVED_SPEC_REV2.id, 1);
    // The editor now shows the reverted frame, not the one we moved off.
    expect((screen.getByLabelText(/input frame/i) as HTMLTextAreaElement).value).toContain(
      '"field": "b"',
    );
  });
});

describe("ChartPage diff", () => {
  beforeEach(() => {
    vi.mocked(listSources).mockResolvedValue([SOURCE]);
    vi.mocked(getSpec).mockResolvedValue(SAVED_SPEC_REV2);
    vi.mocked(loadFlint).mockResolvedValue(HONEST_FLINT);
    vi.mocked(savedBind).mockResolvedValue(honestEnvelope(3));
    vi.mocked(listRevisions).mockResolvedValue([
      {
        revision_number: 2,
        created_at: "2026-08-30T12:02:00Z",
        content_hash: "hash-2",
        authored_flint_version: "0.5.1",
        current: true,
      },
      {
        revision_number: 1,
        created_at: "2026-08-30T12:01:00Z",
        content_hash: "hash-1",
        authored_flint_version: "0.5.1",
        current: false,
      },
    ]);
    vi.mocked(diffRevisions).mockResolvedValue({
      from_revision: 1,
      to_revision: 2,
      source_schema_only: false,
      hunks: [
        {
          op: "changed",
          path: "/chart_spec/encodings/x/field",
          from_value: "b",
          to_value: "a",
        },
      ],
    });
    vi.mocked(drawChart).mockClear();
  });

  it("loads the latest-edit hunks when History opens", async () => {
    render(
      <MemoryRouter initialEntries={[`/charts/${SAVED_SPEC_REV2.id}`]}>
        <Routes>
          <Route path="/charts/:chartId" element={<ChartPage />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "History" }));
    expect(await screen.findByText("/chart_spec/encodings/x/field")).toBeTruthy();
    expect(screen.getByText("1 hunk")).toBeTruthy();
    expect(vi.mocked(diffRevisions)).toHaveBeenCalledWith(
      getToken,
      SAVED_SPEC_REV2.id,
      1,
      2,
    );
  });

  it("re-fetches when the user picks another pair", async () => {
    vi.mocked(diffRevisions).mockResolvedValueOnce({
      from_revision: 1,
      to_revision: 2,
      source_schema_only: false,
      hunks: [
        {
          op: "changed",
          path: "/chart_spec/encodings/x/field",
          from_value: "b",
          to_value: "a",
        },
      ],
    });
    vi.mocked(diffRevisions).mockResolvedValueOnce({
      from_revision: 2,
      to_revision: 2,
      source_schema_only: false,
      hunks: [],
    });
    render(
      <MemoryRouter initialEntries={[`/charts/${SAVED_SPEC_REV2.id}`]}>
        <Routes>
          <Route path="/charts/:chartId" element={<ChartPage />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "History" }));
    expect(await screen.findByText("/chart_spec/encodings/x/field")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Diff from revision"), {
      target: { value: "2" },
    });
    expect(await screen.findByText("Identical revisions — zero hunks.")).toBeTruthy();
    expect(vi.mocked(diffRevisions).mock.calls.at(-1)).toEqual([
      getToken,
      SAVED_SPEC_REV2.id,
      2,
      2,
    ]);
  });

  it("keeps the previous hunks when a compare fails", async () => {
    vi.mocked(diffRevisions).mockResolvedValueOnce({
      from_revision: 1,
      to_revision: 2,
      source_schema_only: false,
      hunks: [
        {
          op: "changed",
          path: "/chart_spec/encodings/x/field",
          from_value: "b",
          to_value: "a",
        },
      ],
    });
    vi.mocked(diffRevisions).mockRejectedValueOnce(
      new ApiError(500, { error: "internal", message: "compare failed" }),
    );
    render(
      <MemoryRouter initialEntries={[`/charts/${SAVED_SPEC_REV2.id}`]}>
        <Routes>
          <Route path="/charts/:chartId" element={<ChartPage />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "History" }));
    expect(await screen.findByText("/chart_spec/encodings/x/field")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Diff from revision"), {
      target: { value: "2" },
    });
    expect(await screen.findByText("compare failed")).toBeTruthy();
    expect(screen.getByText("/chart_spec/encodings/x/field")).toBeTruthy();
    expect((screen.getByLabelText("Diff from revision") as HTMLSelectElement).value).toBe(
      "1",
    );
  });
});

