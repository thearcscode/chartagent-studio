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
    planSpec: vi.fn(),
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
    remapPreview: vi.fn(),
    diffRevisions: vi.fn(),
  };
});

vi.mock("../lib/flint", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/flint")>();
  return { ...original, loadFlint: vi.fn() };
});

vi.mock("../lib/renderers", () => ({ drawChart: vi.fn() }));

import { createSpec, diffRevisions, getSpec, listRevisions, listSources, planSpec, previewBind, remapPreview, revertSpec, savedBind, updateSpec } from "../lib/charts-api";
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
      { name: "c", type: "BIGINT", bucket: "number" },
      { name: "b", type: "VARCHAR", bucket: "string" },
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
    x_chartagent: { source_schema: { a: "number", b: "string" } },
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
    expect(screen.getByText("c")).toBeTruthy();
    // A drop plus an extra snapshot column is not a rename.
    expect(screen.queryByText("renamed")).toBeNull();
    expect(screen.queryByRole("button", { name: /regenerate/i })).toBeNull();
    expect(screen.queryByText(/schedule/i)).toBeNull();
    expect(screen.queryByText(/light mode/i)).toBeNull();
    expect(screen.getByRole("button", { name: "Remap dropped columns" })).toBeTruthy();

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
    expect(screen.getByText(/raw_sql/)).toBeTruthy();
    expect(screen.getByText(/fix the data/)).toBeTruthy();
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

describe("ChartPage drift remap", () => {
  beforeEach(() => {
    vi.mocked(listSources).mockResolvedValue([SOURCE]);
    vi.mocked(getSpec).mockResolvedValue(SAVED_SPEC);
    vi.mocked(loadFlint).mockResolvedValue(HONEST_FLINT);
    vi.mocked(savedBind).mockResolvedValue(honestEnvelope(3));
    vi.mocked(drawChart).mockClear();
  });

  it("previews the patch then saves the remapped frame through the ordinary save path", async () => {
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

    fireEvent.click(screen.getByRole("button", { name: "Remap dropped columns" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Remap a" }), {
      target: { value: "c" },
    });

    const candidate = {
      chart_spec: {
        chartType: "Bar Chart",
        encodings: { x: { field: "b" }, y: { field: "c" } },
      },
    };
    vi.mocked(remapPreview).mockResolvedValueOnce({
      from_revision: 1,
      to_revision: 2,
      source_schema_only: false,
      hunks: [
        {
          op: "changed",
          path: "/chart_spec/encodings/y/field",
          from_value: "a",
          to_value: "c",
        },
      ],
      content: candidate,
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview patch" }));
    expect(await screen.findByText("spec patch · 1 hunk · no model call")).toBeTruthy();
    expect(screen.getByText("/chart_spec/encodings/y/field")).toBeTruthy();
    expect(vi.mocked(remapPreview).mock.calls.at(-1)?.[2]).toEqual({
      mapping: { a: "c" },
      drifted: [{ name: "a", kind: "dropped", expected: "a", found: null }],
    });
    expect(container.querySelector(".chart-area")?.getAttribute("data-state")).toBe(
      "rendered",
    );

    vi.mocked(previewBind).mockResolvedValueOnce(honestEnvelope(2));
    vi.mocked(updateSpec).mockResolvedValueOnce({
      ...SAVED_SPEC,
      revision_number: 2,
      revision_id: "rev-2",
      content: candidate,
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve and save" }));

    await waitFor(() => {
      expect(vi.mocked(updateSpec)).toHaveBeenCalled();
    });
    expect(vi.mocked(previewBind).mock.calls.at(-1)?.[1]).toEqual({
      content: candidate,
      source_id: SOURCE.id,
      backend: "echarts",
    });
    expect(screen.queryByText("SchemaDriftError")).toBeNull();
    expect(screen.getByText("rev 2")).toBeTruthy();
    await waitFor(() => {
      expect(vi.mocked(drawChart).mock.calls.length).toBe(drawsBefore + 1);
    });
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

/** Honest assemble for every backend the plan tests snap to. */
function honestOption(input: unknown) {
  return {
    _dataLength: (input as { data: { values: unknown[] } }).data.values.length,
    series: [{ type: "bar" }],
  };
}

const PLAN_FLINT: FlintGlobal = {
  assembleECharts: honestOption,
  assembleVegaLite: honestOption,
  assemblePlotly: honestOption,
  assembleChartjs: honestOption,
  assembleExcel: honestOption,
  isExcelSupported: () => true,
  generateOfficeJs: () => ({ code: "async function renderFlintChart() {}" }),
};

/** Stub envelope whose backend is not the picker's default — the snap is
 * load-bearing (Studio ADR-0001 D6). */
function plannedEnvelope(): import("../lib/charts-api").PlanResponse {
  return {
    flint_version: "0.5.1",
    backend: "vegalite",
    input: {
      data: {
        values: [
          { a: 1, b: "x" },
          { a: 2, b: "y" },
          { a: 3, b: "z" },
        ],
      },
      chart_spec: {
        chartType: "Bar Chart",
        encodings: { x: { field: "b" }, y: { field: "a" } },
      },
    },
    row_count: 3,
    elapsed: 0.041,
    warnings: [],
    source_schema: { a: "number", b: "string" },
    plan_elapsed_ms: 2340,
  };
}

function renderNewChart() {
  return render(
    <MemoryRouter initialEntries={["/charts/new"]}>
      <Routes>
        <Route path="/charts/new" element={<ChartPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function fillInstruction(instruction = "revenue by region") {
  fireEvent.change(await screen.findByLabelText("Data source"), {
    target: { value: SOURCE.id },
  });
  fireEvent.change(screen.getByLabelText("Instruction"), {
    target: { value: instruction },
  });
}

describe("ChartPage instruction box", () => {
  beforeEach(() => {
    vi.mocked(listSources).mockResolvedValue([SOURCE]);
    vi.mocked(loadFlint).mockResolvedValue(PLAN_FLINT);
    vi.mocked(planSpec).mockResolvedValue(plannedEnvelope());
    vi.mocked(previewBind).mockResolvedValue({
      ...honestEnvelope(3),
      backend: "vegalite",
    });
    vi.mocked(drawChart).mockClear();
    vi.mocked(planSpec).mockClear();
    vi.mocked(previewBind).mockClear();
    vi.mocked(savedBind).mockClear();
    vi.mocked(createSpec).mockClear();
    vi.mocked(updateSpec).mockClear();
  });

  it("shows the disclosure line on a new chart", async () => {
    renderNewChart();
    expect(
      await screen.findByText(
        /a profile of this source, including sample values, plus your instruction, is sent to the configured model vendor/i,
      ),
    ).toBeTruthy();
    expect(screen.getByLabelText("Instruction")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Plan" })).toBeTruthy();
  });

  it("shows the instruction box on an already-saved chart", async () => {
    vi.mocked(getSpec).mockResolvedValue(SAVED_SPEC);
    vi.mocked(savedBind).mockResolvedValue(honestEnvelope(3));
    renderSavedChart();
    expect(await screen.findByLabelText("Instruction")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Plan" })).toBeTruthy();
    expect(
      screen.getByText(
        /a profile of this source, including sample values, plus your instruction, is sent to the configured model vendor/i,
      ),
    ).toBeTruthy();
  });

  it("draws a planned envelope through the shared compile path and strips rows from the editor", async () => {
    renderNewChart();
    await fillInstruction();
    fireEvent.click(screen.getByRole("button", { name: "Plan" }));

    expect(await screen.findByText(/planner chose/i)).toBeTruthy();
    await waitFor(() => {
      expect(vi.mocked(drawChart)).toHaveBeenCalled();
    });
    expect(vi.mocked(planSpec).mock.calls.at(-1)?.[1]).toEqual({
      instruction: "revenue by region",
      source_id: SOURCE.id,
    });
    const editor = screen.getByLabelText(/input frame/i) as HTMLTextAreaElement;
    expect(editor.value).toContain("Bar Chart");
    expect(editor.value).not.toContain('"data"');
    expect(editor.value).not.toContain('"z"');
  });

  it("snaps the picker to the stub envelope's backend", async () => {
    renderNewChart();
    expect((await screen.findByRole("button", { name: "ECharts" })).className).toContain(
      "is-active",
    );
    await fillInstruction();
    fireEvent.click(screen.getByRole("button", { name: "Plan" }));

    expect(await screen.findByText(/planner chose/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Vega-Lite" }).className).toContain(
      "is-active",
    );
    expect(screen.getByRole("button", { name: "ECharts" }).className).not.toContain(
      "is-active",
    );
  });

  it("shows the plan term on the cost line and drops it on the next bind", async () => {
    renderNewChart();
    await fillInstruction();
    fireEvent.click(screen.getByRole("button", { name: "Plan" }));

    expect(await screen.findByText("3 rows · 41 ms bind · 2 s plan · Vega-Lite")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /bind & draw/i }));
    expect(await screen.findByText("3 rows · 41 ms · Vega-Lite")).toBeTruthy();
    expect(screen.queryByText(/s plan/)).toBeNull();
  });

  it("does not confirm on an unmodified saved chart, and confirms when the editor differs from the revision", async () => {
    vi.mocked(getSpec).mockResolvedValue(SAVED_SPEC);
    vi.mocked(savedBind).mockResolvedValue(honestEnvelope(3));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderSavedChart();
    expect(await screen.findByText("3 rows · 41 ms · ECharts")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Instruction"), {
      target: { value: "revenue by region" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Plan" }));
    await waitFor(() => {
      expect(vi.mocked(planSpec)).toHaveBeenCalled();
    });
    expect(confirm).not.toHaveBeenCalled();

    vi.mocked(planSpec).mockClear();
    fireEvent.change(screen.getByLabelText(/input frame/i), {
      target: { value: FRAME },
    });
    fireEvent.click(screen.getByRole("button", { name: "Plan" }));
    expect(confirm).toHaveBeenCalled();
    expect(vi.mocked(planSpec)).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("saves a re-planned saved chart as the next revision without a second bind", async () => {
    vi.mocked(getSpec).mockResolvedValue(SAVED_SPEC);
    vi.mocked(savedBind).mockResolvedValue(honestEnvelope(3));
    vi.mocked(updateSpec).mockResolvedValue({
      ...SAVED_SPEC,
      revision_number: 2,
      revision_id: "rev-2",
    });
    renderSavedChart();
    expect(await screen.findByText("3 rows · 41 ms · ECharts")).toBeTruthy();
    const savedBindsBeforePlan = vi.mocked(savedBind).mock.calls.length;
    fireEvent.change(screen.getByLabelText("Instruction"), {
      target: { value: "revenue by region" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Plan" }));
    expect(await screen.findByText(/planner chose/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(vi.mocked(updateSpec)).toHaveBeenCalled();
    });
    const payload = vi.mocked(updateSpec).mock.calls.at(-1)?.[2];
    expect(payload?.bind?.rows).toEqual(plannedEnvelope().input.data.values);
    expect(payload?.bind?.backend).toBe("vegalite");
    expect(screen.getByText("rev 2")).toBeTruthy();
    expect(vi.mocked(savedBind).mock.calls.length).toBe(savedBindsBeforePlan);
    expect(vi.mocked(previewBind)).not.toHaveBeenCalled();
  });

  it("does not confirm on a brand-new empty editor", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderNewChart();
    await fillInstruction();
    fireEvent.click(screen.getByRole("button", { name: "Plan" }));

    await waitFor(() => {
      expect(vi.mocked(planSpec)).toHaveBeenCalled();
    });
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("confirms before planning when the editor is dirty, and cancels without sending", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderNewChart();
    await fillInstruction();
    fireEvent.change(screen.getByLabelText(/input frame/i), {
      target: { value: FRAME },
    });
    fireEvent.click(screen.getByRole("button", { name: "Plan" }));

    expect(confirm).toHaveBeenCalled();
    expect(vi.mocked(planSpec)).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("saves a planned draft from the plan's bind, without a second bind", async () => {
    vi.mocked(createSpec).mockResolvedValue(SAVED_SPEC);
    renderNewChart();
    await fillInstruction();
    fireEvent.click(screen.getByRole("button", { name: "Plan" }));
    expect(await screen.findByText(/planner chose/i)).toBeTruthy();
    const bindsBeforeSave = vi.mocked(previewBind).mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(vi.mocked(createSpec)).toHaveBeenCalled();
    });
    const payload = vi.mocked(createSpec).mock.calls.at(-1)?.[1];
    expect(payload?.bind?.rows).toEqual(plannedEnvelope().input.data.values);
    expect(payload?.bind?.backend).toBe("vegalite");
    expect(payload?.content).not.toHaveProperty("data");
    expect(vi.mocked(previewBind).mock.calls.length).toBe(bindsBeforeSave);
    expect(vi.mocked(planSpec).mock.calls.length).toBe(1);
  });

  it("rebinds a planned draft on a backend pick without calling plan again", async () => {
    renderNewChart();
    await fillInstruction();
    fireEvent.click(screen.getByRole("button", { name: "Plan" }));
    expect(await screen.findByText(/planner chose/i)).toBeTruthy();
    vi.mocked(previewBind).mockResolvedValueOnce(honestEnvelope(3));

    fireEvent.click(screen.getByRole("button", { name: "ECharts" }));
    expect(await screen.findByText("3 rows · 41 ms · ECharts")).toBeTruthy();
    expect(vi.mocked(planSpec).mock.calls.length).toBe(1);
    expect(screen.queryByText(/planner chose/i)).toBeNull();
  });

  it("shows an in-flight state while a plan is running", async () => {
    let resolvePlan!: (value: ReturnType<typeof plannedEnvelope>) => void;
    vi.mocked(planSpec).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePlan = resolve;
        }),
    );
    renderNewChart();
    await fillInstruction();
    fireEvent.click(screen.getByRole("button", { name: "Plan" }));

    expect(await screen.findByText("Planning…")).toBeTruthy();
    resolvePlan(plannedEnvelope());
    expect(await screen.findByText(/planner chose/i)).toBeTruthy();
  });
});

describe("ChartPage plan errors", () => {
  beforeEach(() => {
    vi.mocked(listSources).mockResolvedValue([SOURCE]);
    vi.mocked(loadFlint).mockResolvedValue(PLAN_FLINT);
    vi.mocked(drawChart).mockClear();
  });

  async function planAndFail(error: ApiError) {
    vi.mocked(planSpec).mockRejectedValueOnce(error);
    renderNewChart();
    await fillInstruction();
    fireEvent.click(screen.getByRole("button", { name: "Plan" }));
  }

  it("renders an inexpressible request", async () => {
    await planAndFail(
      new ApiError(422, {
        error: "inexpressible_request",
        message: "cannot express this as a chart",
        bucket: 2,
      }),
    );
    expect(await screen.findByText(/cannot express this as a chart/i)).toBeTruthy();
    expect(screen.getByText(/bucket: 2/)).toBeTruthy();
  });

  it("renders an unanswerable instruction naming the missing columns", async () => {
    await planAndFail(
      new ApiError(422, {
        error: "unanswerable_instruction",
        message: "column is missing",
        kind: "missing_column",
        keys: ["revenue"],
      }),
    );
    expect(await screen.findByText(/column is missing/i)).toBeTruthy();
    expect(screen.getByText(/offending: revenue/)).toBeTruthy();
  });

  it("renders an unanswerable instruction naming the missing roles", async () => {
    await planAndFail(
      new ApiError(422, {
        error: "unanswerable_instruction",
        message: "no numeric column to plot",
        kind: "missing_role",
        keys: ["number"],
      }),
    );
    expect(await screen.findByText(/no numeric column to plot/i)).toBeTruthy();
    expect(screen.getByText(/offending: number/)).toBeTruthy();
  });

  it("renders a backend capability mismatch", async () => {
    await planAndFail(
      new ApiError(422, {
        error: "backend_capability",
        message: "excel cannot facet",
        kind: "facet",
        keys: ["column"],
        chart_type: "Bar Chart",
        backend: "excel",
        pin: "0.1.0",
      }),
    );
    expect(await screen.findByText(/excel cannot facet/i)).toBeTruthy();
    expect(screen.getByText(/chart type: Bar Chart/)).toBeTruthy();
  });

  it("renders a planner failure", async () => {
    await planAndFail(
      new ApiError(502, {
        error: "planner_failure",
        message: "step 1 failed",
        reason: "retries_exhausted",
      }),
    );
    expect(await screen.findByText(/step 1 failed/i)).toBeTruthy();
    expect(screen.getByText(/reason: retries_exhausted/)).toBeTruthy();
  });

  it("renders a vendor outage as temporary and upstream", async () => {
    await planAndFail(
      new ApiError(502, {
        error: "model_vendor_unavailable",
        request_id: "req-1",
      }),
    );
    expect(
      await screen.findByText(/model vendor is temporarily unavailable/i),
    ).toBeTruthy();
    expect(screen.getByText(/request id: req-1/)).toBeTruthy();
  });

  it("renders a row-cap refusal", async () => {
    await planAndFail(
      new ApiError(422, {
        error: "row_cap_exceeded",
        message: "bind returned 100001 rows, over the configured cap of 100000",
        row_count: 100001,
        cap: 100000,
      }),
    );
    expect(await screen.findByText(/over the configured cap/i)).toBeTruthy();
    expect(screen.getByText(/100001 rows over the cap of 100000/)).toBeTruthy();
  });

  it("renders a 503 when too many plans are in flight", async () => {
    await planAndFail(
      new ApiError(503, {
        error: "plan_busy",
        message: "try again shortly",
      }),
    );
    expect(await screen.findByText(/try again shortly/i)).toBeTruthy();
  });
});


