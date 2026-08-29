/** Serving the pin, client side (ADR-0006 D6): the app was built against one
 * Flint pin — recorded in `../flint-pin.json` and verified in CI against the
 * library checkout at `LIBRARY_GIT_SHA`. At runtime the client fetches the
 * server's pin document, refuses a mismatch with the built-against value
 * (fail loud, both hashes named), then verifies the served bytes against the
 * pin before executing them. The bundle never comes from a CDN.
 */

import type { ChartAssemblyInput } from "flint-chart";

import { apiFetch } from "../api";
import buildPin from "../flint-pin.json";

export interface FlintGlobal {
  assembleECharts(input: ChartAssemblyInput): unknown;
  assembleVegaLite(input: ChartAssemblyInput): unknown;
  assemblePlotly(input: ChartAssemblyInput): unknown;
  assembleChartjs(input: ChartAssemblyInput): unknown;
  assembleExcel(input: ChartAssemblyInput): unknown;
  isExcelSupported(chartType: string): boolean;
}

export interface FlintPin {
  flint_version: string;
  bundle_sha256: string;
  url: string;
}

/** The value the app was built against. */
export const BUILT_AGAINST = {
  flintVersion: buildPin.flint_version,
  bundleSha256: buildPin.bundle_sha256,
} as const;

export class FlintPinMismatchError extends Error {
  constructor(
    readonly detail: string,
  ) {
    super(detail);
    this.name = "FlintPinMismatchError";
  }
}

/** The pure comparison — the component-test seam. A mismatch fails loud and
 * names both hashes; it never offers a historical bundle. */
export function assertServedPinMatchesBuild(served: {
  bundle_sha256: string;
  flint_version: string;
}): void {
  if (served.bundle_sha256 !== BUILT_AGAINST.bundleSha256) {
    throw new FlintPinMismatchError(
      `Flint pin mismatch: the server serves bundle ${served.bundle_sha256} ` +
        `(flint ${served.flint_version}) but this app was built against ` +
        `${BUILT_AGAINST.bundleSha256} (flint ${BUILT_AGAINST.flintVersion}). ` +
        `Rebuild the app against the deployed library.`,
    );
  }
}

export async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** Served-byte integrity: the bytes must hash to the pin they were fetched
 * under, or the cache/CDN/proxy between us and the server is corrupt. */
export async function verifyBundleBytes(
  bytes: ArrayBuffer,
  expectedSha256: string,
): Promise<void> {
  const actual = await sha256Hex(bytes);
  if (actual !== expectedSha256) {
    throw new FlintPinMismatchError(
      `Flint bundle integrity failure: the served bytes hash to ${actual}, ` +
        `not the pinned ${expectedSha256}. Refusing to execute them.`,
    );
  }
}

function injectScript(url: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = url;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Flint bundle failed to execute"));
    document.head.appendChild(script);
  });
}

let loading: Promise<FlintGlobal> | null = null;

type GetToken = () => Promise<string | null>;

/** Load the pinned bundle once per page lifetime. */
export function loadFlint(getToken: GetToken): Promise<FlintGlobal> {
  loading ??= (async () => {
    const pinResponse = await apiFetch("/api/flint", getToken);
    if (!pinResponse.ok) {
      throw new Error(`Flint pin fetch failed: HTTP ${pinResponse.status}`);
    }
    const pin = (await pinResponse.json()) as FlintPin;
    assertServedPinMatchesBuild(pin);

    const bundleResponse = await apiFetch(pin.url, getToken);
    if (!bundleResponse.ok) {
      throw new Error(`Flint bundle fetch failed: HTTP ${bundleResponse.status}`);
    }
    const bytes = await bundleResponse.arrayBuffer();
    await verifyBundleBytes(bytes, pin.bundle_sha256);

    const blobUrl = URL.createObjectURL(new Blob([bytes], { type: "text/javascript" }));
    try {
      await injectScript(blobUrl);
    } finally {
      URL.revokeObjectURL(blobUrl);
    }
    const flint = (globalThis as { Flint?: FlintGlobal }).Flint;
    if (!flint) {
      throw new Error("Flint bundle executed but registered no global");
    }
    return flint;
  })();
  return loading;
}

/** Test seam: drop the memoised bundle. */
export function resetFlintForTests(): void {
  loading = null;
}
