/** The house palette rewrite: renderer-default categorical colours are
 * replaced; deliberate compiler choices are left alone.
 */

import { describe, expect, it } from "vitest";

import { applyHousePalette, HOUSE_PALETTE } from "./palette";

describe("applyHousePalette", () => {
  it("rewrites the ECharts default palette, per series", () => {
    const option = {
      color: ["#5470c6"],
      series: [
        { type: "bar", itemStyle: { color: "#5470c6" } },
        { type: "bar", itemStyle: { color: "#91cc75" } },
      ],
    };
    applyHousePalette(option, "echarts");
    expect(option.color).toEqual(HOUSE_PALETTE);
    expect(option.series[0].itemStyle.color).toBe(HOUSE_PALETTE[0]);
    expect(option.series[1].itemStyle.color).toBe(HOUSE_PALETTE[1]);
  });

  it("leaves a deliberate ECharts series colour alone", () => {
    const option = {
      series: [{ type: "bar", itemStyle: { color: "#123456" } }],
    };
    applyHousePalette(option, "echarts");
    expect(option.series[0].itemStyle.color).toBe("#123456");
  });

  it("rewrites the Vega-Lite default scheme, keeping deliberate schemes", () => {
    const defaulted = { encoding: { color: { scale: { scheme: "tableau10" } } } };
    applyHousePalette(defaulted, "vegalite");
    expect(defaulted.encoding.color.scale).toEqual({ range: HOUSE_PALETTE });

    const deliberate = { encoding: { color: { scale: { scheme: "reds" } } } };
    applyHousePalette(deliberate, "vegalite");
    expect(deliberate.encoding.color.scale).toEqual({ scheme: "reds" });
  });

  it("houses an uncoloured Vega-Lite mark via the config default slot", () => {
    const option: Record<string, unknown> = { mark: "bar", config: {} };
    applyHousePalette(option, "vegalite");
    const config = option.config as { mark: { color: string } };
    expect(config.mark.color).toBe(HOUSE_PALETTE[0]);
  });

  it("rewrites Plotly default trace colours and sets the colorway", () => {
    const option = {
      layout: {},
      data: [{ marker: { color: "#636efa" } }, { marker: { color: "#EF553B" } }],
    };
    applyHousePalette(option, "plotly");
    expect(option.layout).toMatchObject({ colorway: HOUSE_PALETTE });
    expect(option.data[0].marker.color).toBe(HOUSE_PALETTE[0]);
    expect(option.data[1].marker.color).toBe(HOUSE_PALETTE[1]);
  });

  it("rewrites Chart.js default dataset colours, keeping the alpha", () => {
    const option = {
      data: {
        datasets: [
          { backgroundColor: "rgba(54, 162, 235, 0.6)", borderColor: "#36a2eb" },
        ],
      },
    };
    applyHousePalette(option, "chartjs");
    expect(option.data.datasets[0].borderColor).toBe(HOUSE_PALETTE[0]);
    expect(option.data.datasets[0].backgroundColor).toBe(
      "rgba(0, 114, 178, 0.6)",
    );
  });

  it("is a no-op for excel and for non-object options", () => {
    const option = { schema: "flint.excel.chart/v1", data: [["a"], [1]] };
    applyHousePalette(option, "excel");
    expect(option).toEqual({ schema: "flint.excel.chart/v1", data: [["a"], [1]] });
    expect(applyHousePalette(null, "echarts")).toBeNull();
  });
});
