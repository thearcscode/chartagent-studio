/** Rail-independent refresh logic: the failure a refresh shows, and the
 * plain lines for a mapped error. Shared by the Flint chart page and the
 * custom-rail page, so both say the same thing. */

import { ApiError, type SourceOut } from "./charts-api";
import type { DriftedField } from "./drift";

export type RefreshFailure =
  | { kind: "drift"; message: string; drifted: DriftedField[] }
  | { kind: "other"; lines: string[] };

export function sourceName(source: SourceOut): string {
  if (source.kind === "upload") return source.original_filename ?? "upload";
  const url = source.url ?? "";
  const segment = url.replace(/\/+$/, "").split("/").pop();
  return segment ?? url;
}

/** The mapped error, rendered with its typed fields — the offending key,
 * chart type, backend and pin, never "something went wrong". */
export function errorLines(error: ApiError): string[] {
  const body = error.body;
  const lines: string[] = [];
  if (body.error === "model_vendor_unavailable") {
    lines.push("The model vendor is temporarily unavailable. Try again shortly.");
    if (body.request_id) lines.push(`request id: ${body.request_id}`);
    return lines;
  }
  const headline = body.message ?? body.detail ?? `HTTP ${error.status}`;
  lines.push(headline);
  const fields: string[] = [];
  if (body.kind) fields.push(`kind: ${body.kind}`);
  if (body.keys?.length) fields.push(`offending: ${body.keys.join(", ")}`);
  if (body.chart_type) fields.push(`chart type: ${body.chart_type}`);
  if (body.backend) fields.push(`backend: ${body.backend}`);
  if (body.pin) fields.push(`pin: ${body.pin}`);
  if (body.stage) fields.push(`stage: ${body.stage}`);
  if (body.bucket !== undefined) fields.push(`bucket: ${body.bucket}`);
  if (body.reason) fields.push(`reason: ${body.reason}`);
  if (body.extra) fields.push(`extra: ${body.extra}`);
  if (body.row_count !== undefined && body.cap !== undefined) {
    fields.push(`${body.row_count} rows over the cap of ${body.cap}`);
  }
  if (fields.length) lines.push(fields.join(" · "));
  for (const field of body.drifted ?? []) {
    lines.push(
      `${field.name}: expected ${field.expected ?? "—"}, found ${field.found ?? "—"} (${field.kind})`,
    );
  }
  if (body.request_id) lines.push(`request id: ${body.request_id}`);
  return lines;
}

/** Any caught value → displayable lines: the mapped error's typed fields
 * when the server sent them, the plain message otherwise. */
export function toErrorLines(error: unknown): string[] {
  return error instanceof ApiError
    ? errorLines(error)
    : [error instanceof Error ? error.message : String(error)];
}

/** A failed refresh as the page shows it: schema drift opens the recovery
 * table, anything else is plain lines. */
export function refreshFailure(error: unknown): RefreshFailure {
  if (error instanceof ApiError && error.body.error === "schema_drift") {
    return {
      kind: "drift",
      message: error.body.message ?? "Schema drift",
      drifted: error.body.drifted ?? [],
    };
  }
  return { kind: "other", lines: toErrorLines(error) };
}

/** What the instruction box hands the chart page it navigates to after a
 * custom-rail plan (#49): the plan's wall time, and the failure of the one
 * bind that followed the save, if it failed. */
export interface RecipeOpenState {
  planElapsedMs: number;
  refreshFailure?: RefreshFailure;
}
