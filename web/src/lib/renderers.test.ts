/** ECharts measures the host at init. ChartPage hides an empty
 * `.chart-canvas` (`display: none`), so a bind that then draws into it
 * would paint a 0×0 canvas unless the draw pins the compiled size.
 *
 * @vitest-environment jsdom
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { BASE_SIZE } from "./compile";

const init = vi.hoisted(() =>
  vi.fn(() => ({
    setOption: vi.fn(),
    dispose: vi.fn(),
  })),
);

const newPlot = vi.hoisted(() => vi.fn(async () => undefined));
const purge = vi.hoisted(() => vi.fn());

vi.mock("echarts", () => ({ init }));
vi.mock("plotly.js-dist-min", () => ({ newPlot, purge }));

import { drawChart } from "./renderers";

describe("drawChart echarts size", () => {
  afterEach(() => {
    init.mockClear();
    newPlot.mockClear();
    document.body.replaceChildren();
  });

  it("pins the compiled size so a display:none host is still drawable", async () => {
    const el = document.createElement("div");
    el.style.display = "none";
    document.body.appendChild(el);

    await drawChart(el, "echarts", { series: [{ type: "bar", data: [1] }] });

    expect(init).toHaveBeenCalledWith(
      el,
      undefined,
      expect.objectContaining({
        renderer: "canvas",
        width: BASE_SIZE.width,
        height: BASE_SIZE.height,
      }),
    );
  });

  it("pins Plotly's layout to the compiled size so a Library card cannot overflow", async () => {
    const el = document.createElement("div");
    document.body.appendChild(el);

    await drawChart(el, "plotly", {
      data: [{ type: "bar", x: ["Q1"], y: [1] }],
      layout: { width: 700, height: 450 },
    });

    expect(newPlot).toHaveBeenCalledWith(
      el,
      [{ type: "bar", x: ["Q1"], y: [1] }],
      expect.objectContaining({
        width: BASE_SIZE.width,
        height: BASE_SIZE.height,
        autosize: false,
      }),
      expect.objectContaining({ displaylogo: false, responsive: false }),
    );
  });
});
