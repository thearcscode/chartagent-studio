/** Typed calls for the ticket-#74 seam: sources, specs, binds. The error
 * body is the server's mapping table (ADR-0006 D13) — typed fields carried,
 * never flattened to "something went wrong".
 */

import { apiFetch } from "../api";
import type { Backend } from "./backends";

type GetToken = () => Promise<string | null>;

export interface SourceOut {
  id: string;
  kind: "upload" | "url";
  original_filename: string | null;
  url: string | null;
  byte_size: number | null;
  created_at: string;
}

export interface AdvisoryOut {
  code: string;
  message: string;
}

/** Envelope JSON (the three keys) plus diagnostics — exactly what the server
 * returns; never a compiled option. */
export interface BindResponse {
  flint_version: string;
  backend: string;
  input: Record<string, unknown> & { data: { values: Array<Record<string, unknown>> } };
  row_count: number;
  elapsed: number;
  warnings: AdvisoryOut[];
  source_schema: Record<string, string> | null;
}

export interface CacheOut {
  revision_id: string;
  source_id: string;
  row_count: number;
  elapsed_ms: number;
  bound_at: string;
}

export interface SpecOut {
  id: string;
  title: string;
  kind: string;
  revision_id: string;
  revision_number: number;
  content: Record<string, unknown>;
  content_hash: string;
  authored_flint_version: string | null;
  default_source_id: string | null;
  created_at: string;
  updated_at: string;
  cache: CacheOut | null;
}

/** The bound result handed back on save — the save-writes-cache handoff
 * (ADR-0007 D8 erratum). The server re-checks honesty before writing. */
export interface BindBlock {
  backend: Backend;
  content: Record<string, unknown>;
  rows: Array<Record<string, unknown>>;
  elapsed_ms: number;
  source_schema: Record<string, string> | null;
}

/** The mapped error body: a stable code, a message, and the typed fields the
 * UI renders (offending keys, chart type, backend, pin, drifted fields). */
export interface ApiErrorBody {
  error: string;
  message?: string;
  kind?: string;
  keys?: string[];
  chart_type?: string;
  backend?: string;
  pin?: string;
  stage?: string;
  drifted?: Array<{ name: string; kind: string; expected: string; found: string }>;
  row_count?: number;
  cap?: number;
  reason?: string;
  path?: string;
  request_id?: string;
  detail?: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: ApiErrorBody,
  ) {
    super(body.message ?? body.detail ?? `HTTP ${status}`);
    this.name = "ApiError";
  }
}

async function parseResponse(response: Response): Promise<unknown> {
  const body: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(response.status, body as ApiErrorBody);
  }
  return body;
}

async function request(
  getToken: GetToken,
  method: string,
  path: string,
  payload?: unknown,
): Promise<unknown> {
  const response = await apiFetch(path, getToken, {
    method,
    headers: payload === undefined ? undefined : { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  return parseResponse(response);
}

export async function listSources(getToken: GetToken): Promise<SourceOut[]> {
  return (await request(getToken, "GET", "/api/sources")) as SourceOut[];
}

export async function uploadSource(getToken: GetToken, file: File): Promise<SourceOut> {
  const form = new FormData();
  form.append("file", file);
  const response = await apiFetch("/api/sources/upload", getToken, {
    method: "POST",
    body: form,
  });
  return (await parseResponse(response)) as SourceOut;
}

export async function registerUrlSource(
  getToken: GetToken,
  url: string,
): Promise<SourceOut> {
  return (await request(getToken, "POST", "/api/sources", { url })) as SourceOut;
}

export async function getSpec(getToken: GetToken, chartId: string): Promise<SpecOut> {
  return (await request(getToken, "GET", `/api/specs/${chartId}`)) as SpecOut;
}

export interface SpecSavePayload {
  content: Record<string, unknown>;
  source_id?: string;
  title?: string;
  bind?: BindBlock;
}

export async function createSpec(
  getToken: GetToken,
  payload: SpecSavePayload & { source_id: string },
): Promise<SpecOut> {
  return (await request(getToken, "POST", "/api/specs", payload)) as SpecOut;
}

export async function updateSpec(
  getToken: GetToken,
  chartId: string,
  payload: SpecSavePayload,
): Promise<SpecOut> {
  return (await request(getToken, "PUT", `/api/specs/${chartId}`, payload)) as SpecOut;
}

/** The unsaved-frame bind: writes neither cache nor run. */
export async function previewBind(
  getToken: GetToken,
  payload: { content: Record<string, unknown>; source_id: string; backend: Backend },
): Promise<BindResponse> {
  return (await request(getToken, "POST", "/api/specs/bind", payload)) as BindResponse;
}

/** The user-initiated bind on a saved chart: writes a run, replaces the
 * cache on success. */
export async function savedBind(
  getToken: GetToken,
  chartId: string,
  payload: { backend: Backend; source_id?: string; trigger: "open" | "backend_switch" },
): Promise<BindResponse> {
  return (await request(
    getToken,
    "POST",
    `/api/specs/${chartId}/bind`,
    payload,
  )) as BindResponse;
}
