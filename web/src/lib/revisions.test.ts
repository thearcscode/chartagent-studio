/** authored_flint_version is displayed and never branched on: the note
 * names the other pin, and nothing here offers to load it. */

import { describe, expect, it } from "vitest";

import { pinNote } from "./revisions";

describe("pinNote", () => {
  it("is silent when the revision was saved under the served pin", () => {
    expect(pinNote("0.5.1", "0.5.1")).toBeNull();
  });

  it("is silent when a recipe has no authored pin", () => {
    expect(pinNote(null, "0.5.1")).toBeNull();
  });

  it("names the other pin and does not mention loading it", () => {
    const note = pinNote("0.2.1", "0.5.1");
    expect(note).toBe("Saved under Flint 0.2.1");
    expect(note).not.toMatch(/load/i);
  });
});
