/** The honesty guard, tested without a browser: a compiled point count that
 * disagrees with the bind's row count refuses, names the drop, and yields no
 * option to draw (the chart area stays empty). Also: the palette lands on
 * the assembled option, and `baseSize` is pinned on every compile.
 */

import { describe, expect, it } from "vitest";

import type { BindResponse } from "./charts-api";
import { BASE_SIZE, compileEnvelope, compiledPointCount, compiledSeriesCount } from "./compile";
import type { FlintGlobal } from "./flint";
import { HOUSE_PALETTE } from "./palette";

const ROWS = [
  { a: 1, b: "x" },
  { a: 2, b: "y" },
  { a: 3, b: "z" },
];

function envelope(rowCount = ROWS.length): BindResponse {
  return {
    flint_version: "0.5.1",
    backend: "echarts",
    input: {
      data: { values: ROWS },
      chart_spec: {
        chartType: "Bar Chart",
        encodings: { x: { field: "b" }, y: { field: "a" } },
      },
    },
    row_count: rowCount,
    elapsed: 0.041,
    warnings: [],
    source_schema: {},
  };
}

/** A fake bundle: assembles the ECharts-shaped option the real one would —
 * one point per row — unless told to drop some. */
function fakeFlint(dropRows = 0): FlintGlobal {
  const option = {
    series: [{ type: "bar", data: [1, 2, 3], itemStyle: { color: "#5470c6" } }],
    color: ["#5470c6"],
    _dataLength: ROWS.length - dropRows,
    _warnings: [{ severity: "info", code: "legend_collapsed", message: "…" }],
  };
  return {
    assembleECharts: () => structuredClone(option),
    assembleVegaLite: () => ({}),
    assemblePlotly: () => ({}),
    assembleChartjs: () => ({}),
    assembleExcel: () => ({}),
    isExcelSupported: () => true,
    generateOfficeJs: () => ({ code: "" }),
  };
}

describe("compileEnvelope", () => {
  it("compiles when the point count matches the row count", () => {
    const outcome = compileEnvelope(fakeFlint(), envelope(), "echarts");
    expect(outcome.kind).toBe("compiled");
    if (outcome.kind !== "compiled") return;
    expect(outcome.pointCount).toBe(3);
    expect(outcome.compileWarnings.map((w) => w.code)).toEqual([
      "legend_collapsed",
    ]);
  });

  it("pins baseSize and canvasSize on the input the assembler sees", () => {
    let seen: { chart_spec?: Record<string, unknown> } = {};
    const flint: FlintGlobal = {
      ...fakeFlint(),
      assembleECharts: (input) => {
        seen = input;
        return { _dataLength: 3 };
      },
    };
    compileEnvelope(flint, envelope(), "echarts");
    expect(seen.chart_spec?.baseSize).toEqual(BASE_SIZE);
    expect(seen.chart_spec?.canvasSize).toEqual(BASE_SIZE);
  });

  it("refuses a row-count mismatch and names the drop", () => {
    const outcome = compileEnvelope(fakeFlint(2), envelope(), "echarts");
    expect(outcome.kind).toBe("refusal");
    if (outcome.kind !== "refusal") return;
    // The honesty guard is bug-grade: error tone, not amber.
    expect(outcome.tone).toBe("error");
    // Names the drop: how many rows, how many points, how many lost.
    expect(outcome.reason).toContain("3 rows");
    expect(outcome.reason).toContain("1 point");
    expect(outcome.reason).toContain("2 rows");
    expect(outcome.reason).toContain("silently dropped");
    // Nothing to draw: a refusal carries no option, so the area stays empty.
    expect("option" in outcome).toBe(false);
  });

  it("refuses when the compiled option exposes no point count", () => {
    const flint: FlintGlobal = { ...fakeFlint(), assembleECharts: () => ({}) };
    const outcome = compileEnvelope(flint, envelope(), "echarts");
    expect(outcome.kind).toBe("refusal");
    if (outcome.kind !== "refusal") return;
    expect(outcome.reason).toContain("no point count");
  });

  it("treats an assembler throw as realised capability — amber, named copy", () => {
    const flint: FlintGlobal = {
      ...fakeFlint(),
      assembleECharts: () => {
        throw new Error("boxplot needs a tooltip channel");
      },
    };
    const outcome = compileEnvelope(flint, envelope(), "echarts");
    expect(outcome.kind).toBe("refusal");
    if (outcome.kind !== "refusal") return;
    expect(outcome.tone).toBe("amber");
    expect(outcome.reason).toContain("This app does not support this chart");
    expect(outcome.reason).toContain("boxplot needs a tooltip channel");
    expect("option" in outcome).toBe(false);
  });

  it("applies the house palette to the assembled option", () => {
    const outcome = compileEnvelope(fakeFlint(), envelope(), "echarts");
    if (outcome.kind !== "compiled") throw new Error("expected compiled");
    const option = outcome.option as {
      color: string[];
      series: Array<{ itemStyle: { color: string } }>;
    };
    expect(option.color).toEqual(HOUSE_PALETTE);
    expect(option.series[0].itemStyle.color).toBe(HOUSE_PALETTE[0]);
  });
});

describe("compiledPointCount", () => {
  it("reads _dataLength, then data.values, then the excel shape", () => {
    expect(compiledPointCount({ _dataLength: 7 })).toBe(7);
    expect(compiledPointCount({ data: { values: [1, 2] } })).toBe(2);
    expect(
      compiledPointCount({ schema: "flint.excel.chart/v1", data: [["h"], ["r"]] }),
    ).toBe(1);
    expect(compiledPointCount({})).toBeNull();
    expect(compiledPointCount(null)).toBeNull();
  });
});

describe("compiledSeriesCount", () => {
  it("counts ECharts series, then Plotly data, then Chart.js datasets", () => {
    expect(compiledSeriesCount({ series: [{ type: "bar" }, { type: "line" }] })).toBe(2);
    expect(compiledSeriesCount({ data: [{ type: "bar" }] })).toBe(1);
    expect(compiledSeriesCount({ data: { datasets: [{}, {}] } })).toBe(2);
    expect(compiledSeriesCount({})).toBe(0);
  });
});
