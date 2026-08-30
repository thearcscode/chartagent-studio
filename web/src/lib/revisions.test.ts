/** authored_flint_version is displayed and never branched on: the note
 * names the other pin, and nothing here offers to load it. */

import { describe, expect, it } from "vitest";

import { defaultDiffPair, pinNote } from "./revisions";

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

describe("defaultDiffPair", () => {
  it("diffs the newest revision against the one under it", () => {
    expect(
      defaultDiffPair([
        {
          revision_number: 3,
          created_at: "2026-08-30T12:03:00Z",
          content_hash: "h3",
          authored_flint_version: "0.5.1",
          current: true,
        },
        {
          revision_number: 2,
          created_at: "2026-08-30T12:02:00Z",
          content_hash: "h2",
          authored_flint_version: "0.5.1",
          current: false,
        },
        {
          revision_number: 1,
          created_at: "2026-08-30T12:01:00Z",
          content_hash: "h1",
          authored_flint_version: "0.5.1",
          current: false,
        },
      ]),
    ).toEqual([2, 3]);
  });

  it("diffs a single revision against itself", () => {
    expect(
      defaultDiffPair([
        {
          revision_number: 1,
          created_at: "2026-08-30T12:01:00Z",
          content_hash: "h1",
          authored_flint_version: "0.5.1",
          current: true,
        },
      ]),
    ).toEqual([1, 1]);
  });

  it("is silent when there is no history", () => {
    expect(defaultDiffPair([])).toBeNull();
  });
});
