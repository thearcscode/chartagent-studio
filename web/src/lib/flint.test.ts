/** The pin check, tested without a browser: a served hash that disagrees
 * with the built-against value fails loud and names both hashes; served
 * bytes that don't hash to the pin are refused before execution.
 */

import { describe, expect, it } from "vitest";

import {
  assertServedPinMatchesBuild,
  BUILT_AGAINST,
  FlintPinMismatchError,
  sha256Hex,
  verifyBundleBytes,
} from "./flint";

describe("assertServedPinMatchesBuild", () => {
  it("accepts the built-against pin", () => {
    expect(() =>
      assertServedPinMatchesBuild({
        bundle_sha256: BUILT_AGAINST.bundleSha256,
        flint_version: BUILT_AGAINST.flintVersion,
      }),
    ).not.toThrow();
  });

  it("fails loud on a mismatch and names both hashes", () => {
    const served = { bundle_sha256: "0".repeat(64), flint_version: "9.9.9" };
    let caught: unknown;
    try {
      assertServedPinMatchesBuild(served);
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(FlintPinMismatchError);
    const message = (caught as Error).message;
    expect(message).toContain("0".repeat(64));
    expect(message).toContain(BUILT_AGAINST.bundleSha256);
    expect(message).toContain("9.9.9");
    expect(message).toContain(BUILT_AGAINST.flintVersion);
  });
});

describe("verifyBundleBytes", () => {
  it("accepts bytes that hash to the pin", async () => {
    const bytes = new TextEncoder().encode("the pinned bundle").buffer;
    await expect(
      verifyBundleBytes(bytes, await sha256Hex(bytes)),
    ).resolves.toBeUndefined();
  });

  it("refuses bytes that hash to anything else", async () => {
    const bytes = new TextEncoder().encode("tampered bundle").buffer;
    await expect(verifyBundleBytes(bytes, "0".repeat(64))).rejects.toThrow(
      FlintPinMismatchError,
    );
  });
});
