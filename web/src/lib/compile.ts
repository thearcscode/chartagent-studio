/** The browser compile step (ADR-0006 D4): load bundle → assemble → house
 * palette → compare the compiled point count to `envelope.row_count` → draw
 * or refuse and name the drop. The server never ships a compiled option;
 * the browser never binds.
 */

import type { ChartAssemblyInput, ChartWarning } from "flint-chart";

import type { Backend } from "./backends";
import type { BindResponse } from "./charts-api";
import type { FlintGlobal } from "./flint";
import { applyHousePalette } from "./palette";

/** `baseSize` is pinned on every compile — the size layout aims for, with
 * `canvasSize` pinned to match so the compiled option cannot stretch beyond
 * it (the library's `pinSize`, ported one for one). */
export const BASE_SIZE = { width: 640, height: 400 } as const;

const ASSEMBLERS = {
  echarts: "assembleECharts",
  vegalite: "assembleVegaLite",
  plotly: "assemblePlotly",
  chartjs: "assembleChartjs",
  excel: "assembleExcel",
} as const satisfies Record<Backend, keyof FlintGlobal>;

export interface Compiled {
  kind: "compiled";
  /** The assembled option, house palette applied. `_warnings` and friends
   * stay on it — they are compiler metadata, read here, never drawn. */
  option: Record<string, unknown>;
  compileWarnings: ChartWarning[];
  pointCount: number;
}

export interface Refusal {
  kind: "refusal";
  /** `error` for the honesty guard (a silent row-drop is bug-grade);
   * `amber` for realised capability — a valid document this pin cannot
   * render. The chart area stays empty either way. */
  tone: "amber" | "error";
  /** Names the drop — never "something went wrong". */
  reason: string;
}

export type CompileOutcome = Compiled | Refusal;

/** The compiled point count — the library's `tools/flint-lib.mjs`
 * `rowCount`, ported one for one. */
export function compiledPointCount(output: unknown): number | null {
  if (!output || typeof output !== "object") return null;
  const record = output as Record<string, unknown>;
  if (typeof record._dataLength === "number") return record._dataLength;
  const data = record.data as Record<string, unknown> | undefined;
  if (Array.isArray(data?.values)) return data.values.length;
  if (record.schema === "flint.excel.chart/v1" && Array.isArray(record.data)) {
    return Math.max(0, record.data.length - 1);
  }
  return null;
}

function pinSize(input: ChartAssemblyInput): ChartAssemblyInput {
  return {
    ...input,
    chart_spec: {
      ...input.chart_spec,
      baseSize: { ...BASE_SIZE },
      canvasSize: { ...BASE_SIZE },
    },
  };
}

function compileWarningsOf(option: unknown): ChartWarning[] {
  if (!option || typeof option !== "object") return [];
  const warnings = (option as Record<string, unknown>)._warnings;
  return Array.isArray(warnings) ? (warnings as ChartWarning[]) : [];
}

/** Assemble the envelope's input for one backend and check the honesty
 * guard: the compiled point count must equal the bind's row count, or the
 * chart would silently drop rows. */
export function compileEnvelope(
  flint: FlintGlobal,
  envelope: BindResponse,
  backend: Backend,
): CompileOutcome {
  const assemble = flint[ASSEMBLERS[backend]];
  let option: unknown;
  try {
    option = assemble(
      pinSize(envelope.input as unknown as ChartAssemblyInput),
    ) as unknown;
  } catch (error) {
    // Realised capability after compile — the served pin cannot render this
    // chart. Amber, with the ticket's copy; never an offer of a historical
    // bundle.
    const detail = error instanceof Error ? error.message : String(error);
    return {
      kind: "refusal",
      tone: "amber",
      reason: `This app does not support this chart: ${detail}`,
    };
  }
  if (!option || typeof option !== "object") {
    return {
      kind: "refusal",
      tone: "amber",
      reason: `This app does not support this chart: the ${backend} compiler returned no option object for it.`,
    };
  }
  applyHousePalette(option, backend);
  const pointCount = compiledPointCount(option);
  if (pointCount === null) {
    return {
      kind: "refusal",
      tone: "error",
      reason:
        `Refused to draw: the compiled ${backend} chart exposes no point ` +
        `count, so the ${envelope.row_count} bound rows cannot be accounted ` +
        `for. No partial render.`,
    };
  }
  if (pointCount !== envelope.row_count) {
    const dropped = envelope.row_count - pointCount;
    return {
      kind: "refusal",
      tone: "error",
      reason:
        `Refused to draw: the bind returned ${envelope.row_count} rows but ` +
        `the compiled ${backend} chart holds ${pointCount} points — ` +
        `${dropped} ${dropped === 1 ? "row" : "rows"} would be silently ` +
        `dropped. No partial render.`,
    };
  }
  return {
    kind: "compiled",
    option: option as Record<string, unknown>,
    compileWarnings: compileWarningsOf(option),
    pointCount,
  };
}

/** Series count on a compiled ECharts-shaped option — what the Playwright
 * smoke asserts against a real canvas. Other backends expose an array on
 * `data` (Plotly) or `data.datasets` (Chart.js); those are counted too. */
export function compiledSeriesCount(option: Record<string, unknown>): number {
  if (Array.isArray(option.series)) return option.series.length;
  if (Array.isArray(option.data)) {
    const data = option.data as unknown[];
    if (data.length > 0 && typeof data[0] === "object" && data[0] !== null) {
      return data.length;
    }
  }
  const nested = option.data as Record<string, unknown> | undefined;
  if (Array.isArray(nested?.datasets)) return nested.datasets.length;
  return 0;
}
