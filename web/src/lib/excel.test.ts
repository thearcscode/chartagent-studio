/** Excel gating before click: the reason is named, and the gate never
 * reaches the server. */

import { describe, expect, it } from "vitest";

import { excelGate } from "./excel";

const SUPPORTED = new Set(["Bar Chart", "Line Chart", "Scatter Plot"]);
const isExcelSupported = (chartType: string) => SUPPORTED.has(chartType);

function frame(chartType: string, channels: string[] = ["x", "y"]) {
  return {
    chart_spec: {
      chartType,
      encodings: Object.fromEntries(
        channels.map((channel) => [channel, { field: "f" }]),
      ),
    },
  };
}

describe("excelGate", () => {
  it("passes a supported type without facet channels", () => {
    expect(excelGate(frame("Bar Chart"), isExcelSupported)).toEqual({ ok: true });
  });

  it("names a chart type Excel does not draw", () => {
    const gate = excelGate(frame("Regression"), isExcelSupported);
    expect(gate.ok).toBe(false);
    if (!gate.ok) expect(gate.reason).toContain("Regression");
  });

  it("names the facet channel", () => {
    const gate = excelGate(frame("Bar Chart", ["x", "y", "column"]), isExcelSupported);
    expect(gate.ok).toBe(false);
    if (!gate.ok) expect(gate.reason).toContain("column");
  });

  it("refuses an unparseable or shapeless frame", () => {
    expect(excelGate(null, isExcelSupported).ok).toBe(false);
    expect(excelGate({}, isExcelSupported).ok).toBe(false);
    expect(excelGate({ chart_spec: {} }, isExcelSupported).ok).toBe(false);
  });
});
