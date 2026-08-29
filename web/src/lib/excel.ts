/** Excel gating before click (ADR-0006 D4): a chart type outside Excel's
 * set, or a `column`/`row` facet channel, disables the button with the
 * reason named — the refusal is known before any bind. The check runs
 * against the loaded bundle's `isExcelSupported` (the pin's own vocabulary);
 * remaining refusals are realised capability after compile.
 */

export type ExcelGate = { ok: true } | { ok: false; reason: string };

const FACET_CHANNELS = ["column", "row"];

export function excelGate(
  frame: unknown,
  isExcelSupported: (chartType: string) => boolean,
): ExcelGate {
  if (typeof frame !== "object" || frame === null) {
    return { ok: false, reason: "the frame does not parse" };
  }
  const chartSpec = (frame as Record<string, unknown>).chart_spec;
  if (typeof chartSpec !== "object" || chartSpec === null) {
    return { ok: false, reason: "the frame carries no chart_spec" };
  }
  const chartType = (chartSpec as Record<string, unknown>).chartType;
  if (typeof chartType !== "string" || chartType === "") {
    return { ok: false, reason: "the frame names no chart type" };
  }
  if (!isExcelSupported(chartType)) {
    return {
      ok: false,
      reason: `“${chartType}” is not one of the chart types Excel draws`,
    };
  }
  const encodings = (chartSpec as Record<string, unknown>).encodings;
  if (typeof encodings === "object" && encodings !== null) {
    const facets = FACET_CHANNELS.filter((channel) =>
      Object.hasOwn(encodings, channel),
    );
    if (facets.length > 0) {
      return {
        ok: false,
        reason: `Excel draws no facets — the frame uses ${facets.join(" and ")}`,
      };
    }
  }
  return { ok: true };
}
