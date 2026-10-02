/** The custom-rail fixture shell (#32): html and sandbox tokens exactly as
 * the library returned them, plus the wire rows. */

import { apiFetch } from "../api";
import { ApiError, type ApiErrorBody } from "./charts-api";

export interface FixtureShell {
  html: string;
  sandbox: string[];
  rows: Array<Record<string, unknown>>;
}

export async function fetchFixture(
  getToken: () => Promise<string | null>,
  name: string,
): Promise<FixtureShell> {
  const response = await apiFetch(`/api/fixtures/${encodeURIComponent(name)}`, getToken);
  const body: unknown = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, body as ApiErrorBody);
  return body as FixtureShell;
}
