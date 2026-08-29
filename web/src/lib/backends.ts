/** The five backends — the library's `Backend` union, never a hardcoded
 * constant diverging from it. The server enforces the same allowlist via
 * the library's own type. */

export const BACKENDS = ["echarts", "vegalite", "plotly", "chartjs", "excel"] as const;

export type Backend = (typeof BACKENDS)[number];

export const BACKEND_LABELS: Record<Backend, string> = {
  echarts: "ECharts",
  vegalite: "Vega-Lite",
  plotly: "Plotly",
  chartjs: "Chart.js",
  excel: "Excel",
};
