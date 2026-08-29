/** Per-backend dynamic imports (ADR-0006 D6): a renderer's bytes load only
 * when that backend first draws. Renderers come from npm at exact versions —
 * never a CDN. Each draw returns a cleanup so the chart area can be emptied
 * before the next attempt: no partial render, ever.
 */

import type { Backend } from "./backends";
import { BASE_SIZE } from "./compile";

export type DrawCleanup = () => void;

async function drawECharts(el: HTMLElement, option: unknown): Promise<DrawCleanup> {
  const echarts = await import("echarts");
  // ChartPage hides an empty `.chart-canvas` (`display: none`). ECharts
  // measures the host at init, so a 0×0 box here is a successful bind
  // and a blank stage. Pin the same size compile already pinned.
  const chart = echarts.init(el, undefined, {
    renderer: "canvas",
    width: BASE_SIZE.width,
    height: BASE_SIZE.height,
  });
  chart.setOption(option as Parameters<typeof chart.setOption>[0]);
  return () => chart.dispose();
}

async function drawVegaLite(el: HTMLElement, option: unknown): Promise<DrawCleanup> {
  const { default: embed } = await import("vega-embed");
  const result = await embed(el, option as Parameters<typeof embed>[1], {
    actions: false,
  });
  return () => result.finalize();
}

async function drawChartjs(el: HTMLElement, option: unknown): Promise<DrawCleanup> {
  const { Chart, registerables } = await import("chart.js");
  Chart.register(...registerables);
  const canvas = document.createElement("canvas");
  el.appendChild(canvas);
  const chart = new Chart(
    canvas,
    option as ConstructorParameters<typeof Chart>[1],
  );
  return () => {
    chart.destroy();
    canvas.remove();
  };
}

async function drawPlotly(el: HTMLElement, option: unknown): Promise<DrawCleanup> {
  const Plotly = await import("plotly.js-dist-min");
  const spec = option as { data: unknown[]; layout?: Record<string, unknown> };
  // Flint's layout can exceed the host (legend, default 700px width). Pin
  // the compiled size so a Library card cannot spill out of its box.
  const layout = {
    ...spec.layout,
    width: BASE_SIZE.width,
    height: BASE_SIZE.height,
    autosize: false,
  };
  await Plotly.newPlot(el, spec.data, layout, {
    displaylogo: false,
    responsive: false,
  });
  return () => Plotly.purge(el);
}

/** Draw one compiled option. Only the four browser-drawing backends arrive
 * here — Excel compiles but draws in Excel (the amber state names that). */
export async function drawChart(
  el: HTMLElement,
  backend: Exclude<Backend, "excel">,
  option: unknown,
): Promise<DrawCleanup> {
  // Inline size beats `.chart-canvas:empty { display: none }`, which would
  // otherwise leave Vega / Plotly / Chart.js measuring a 0×0 host too.
  el.style.display = "grid";
  el.style.width = `${BASE_SIZE.width}px`;
  el.style.height = `${BASE_SIZE.height}px`;
  switch (backend) {
    case "echarts":
      return drawECharts(el, option);
    case "vegalite":
      return drawVegaLite(el, option);
    case "chartjs":
      return drawChartjs(el, option);
    case "plotly":
      return drawPlotly(el, option);
  }
}
