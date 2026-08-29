/** The house palette, applied to the assembled option — never via
 * `theme_spec` (ADR-0006 D7). Values are the five data-palette hues from
 * `tokens.css` (`--series-1..5`), deliberately identical in both themes;
 * canvas renderers cannot resolve CSS custom properties, so the hexes are
 * repeated here. Chart series are the only thing these hues may touch.
 *
 * The rewrite is conservative: Flint passes each renderer's *default*
 * categorical palette through into the assembled option, and only those
 * recognised defaults are replaced. A colour the compiler chose deliberately
 * (a semantic or diverging scale) is left alone.
 */

import type { Backend } from "./backends";

export const HOUSE_PALETTE = ["#0072b2", "#e69f00", "#56b4e9", "#d55e00", "#7f7f7f"];

const ECHARTS_DEFAULTS = new Set([
  "#5470c6",
  "#91cc75",
  "#fac858",
  "#ee6666",
  "#73c0de",
  "#3ba272",
  "#fc8452",
  "#9a60b4",
  "#ea7ccc",
  "#d48265",
]);

const PLOTLY_DEFAULTS = new Set([
  "#636efa",
  "#ef553b",
  "#00cc96",
  "#ab63fa",
  "#ffa15a",
  "#19d3f3",
  "#ff6692",
  "#b6e880",
  "#ff97ff",
  "#fecb52",
]);

/** Chart.js default hues, keyed by their `r, g, b` triple (backgrounds carry
 * an alpha; borders are the hex). */
const CHARTJS_DEFAULTS = new Map(
  [
    ["#36a2eb", "54, 162, 235"],
    ["#ff6384", "255, 99, 132"],
    ["#4bc0c0", "75, 192, 192"],
    ["#ff9f40", "255, 159, 64"],
    ["#9966ff", "153, 102, 255"],
    ["#ffcd56", "255, 205, 86"],
    ["#c9cbcf", "201, 203, 207"],
  ].map(([hex, rgb]) => [rgb, hex] as const),
);

function hexToRgb(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function houseColor(index: number): string {
  return HOUSE_PALETTE[index % HOUSE_PALETTE.length];
}

function applyECharts(option: Record<string, unknown>): void {
  option.color = [...HOUSE_PALETTE];
  if (!Array.isArray(option.series)) return;
  option.series.forEach((series: unknown, index: number) => {
    if (!isRecord(series) || !isRecord(series.itemStyle)) return;
    const style = series.itemStyle;
    const color = style.color;
    if (typeof color === "string" && ECHARTS_DEFAULTS.has(color.toLowerCase())) {
      style.color = houseColor(index);
    }
  });
}

function applyPlotly(option: Record<string, unknown>): void {
  const layout = isRecord(option.layout) ? option.layout : undefined;
  if (layout) {
    layout.colorway = [...HOUSE_PALETTE];
  }
  if (!Array.isArray(option.data)) return;
  option.data.forEach((trace: unknown, index: number) => {
    if (!isRecord(trace) || !isRecord(trace.marker)) return;
    const marker = trace.marker;
    const color = marker.color;
    if (typeof color === "string" && PLOTLY_DEFAULTS.has(color.toLowerCase())) {
      marker.color = houseColor(index);
    }
  });
}

function applyChartjs(option: Record<string, unknown>): void {
  const data = isRecord(option.data) ? option.data : undefined;
  const datasets = data?.datasets;
  if (!Array.isArray(datasets)) return;
  datasets.forEach((dataset: unknown, index: number) => {
    if (!isRecord(dataset)) return;
    const border = dataset.borderColor;
    if (
      typeof border === "string" &&
      /^#[0-9a-f]{6}$/i.test(border) &&
      CHARTJS_DEFAULTS.has(hexToRgb(border.toLowerCase()))
    ) {
      dataset.borderColor = houseColor(index);
    }
    const background = dataset.backgroundColor;
    if (typeof background === "string") {
      const match = /^rgba\((\d+, \d+, \d+), ([\d.]+)\)$/.exec(background);
      if (match && CHARTJS_DEFAULTS.has(match[1])) {
        dataset.backgroundColor = `rgba(${hexToRgb(houseColor(index))}, ${match[2]})`;
      }
    }
  });
}

function applyVegaLite(option: Record<string, unknown>): void {
  const encoding = isRecord(option.encoding) ? option.encoding : undefined;
  const color = isRecord(encoding?.color) ? encoding.color : undefined;
  const scale = color && isRecord(color.scale) ? color.scale : undefined;
  // "tableau10" is the renderer default categorical scheme; anything else is
  // a deliberate compiler choice.
  if (color && scale?.scheme === "tableau10") {
    color.scale = { range: [...HOUSE_PALETTE] };
  } else if (color === undefined) {
    // No colour encoding: the mark would render in the renderer's default
    // blue. The config default slot is the honest place to house it.
    const config = isRecord(option.config) ? option.config : {};
    const mark = isRecord(config.mark) ? config.mark : {};
    if (mark.color === undefined) {
      mark.color = HOUSE_PALETTE[0];
    }
    config.mark = mark;
    option.config = config;
  }
}

/** Mutates the assembled option in place; returns it for chaining. */
export function applyHousePalette<T>(option: T, backend: Backend): T {
  if (!isRecord(option)) return option;
  switch (backend) {
    case "echarts":
      applyECharts(option);
      break;
    case "plotly":
      applyPlotly(option);
      break;
    case "chartjs":
      applyChartjs(option);
      break;
    case "vegalite":
      applyVegaLite(option);
      break;
    case "excel":
      // Not drawn in the browser; the workbook writer is a later ticket.
      break;
  }
  return option;
}
