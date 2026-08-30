/** The drift table is client-side logic, not chrome (#8): kind drives the
 * status word, additive snapshot columns show as *added · ignored*, and a
 * dropped column is never collapsed with an extra snapshot column into a
 * rename — the library has no producer for that status.
 */

import { describe, expect, it } from "vitest";

import { driftTable, referencedNames } from "./drift";

const DROPPED = {
  name: "a",
  kind: "dropped" as const,
  expected: "a",
  found: null,
};

const RETYPED = {
  name: "churn_rate",
  kind: "retyped" as const,
  expected: "number",
  found: "string",
};

describe("driftTable", () => {
  it("renders a dropped field as three columns with kind as the status word", () => {
    const rows = driftTable({
      drifted: [DROPPED],
      snapshot: [],
      referenced: ["a"],
    });
    expect(rows).toEqual([
      { spec: "a", snapshot: "—", status: "dropped" },
    ]);
  });

  it("names a retype as a retype — expected and found are the buckets, not a remap", () => {
    const rows = driftTable({
      drifted: [RETYPED],
      snapshot: [{ name: "churn_rate", type: "VARCHAR" }],
      referenced: ["churn_rate"],
    });
    expect(rows).toEqual([
      { spec: "churn_rate", snapshot: "churn_rate", status: "retyped" },
    ]);
    expect(rows.some((row) => /remap|cast/i.test(row.status))).toBe(false);
  });

  it("shows snapshot columns the spec does not reference as added · ignored", () => {
    const rows = driftTable({
      drifted: [DROPPED],
      snapshot: [
        { name: "c", type: "BIGINT" },
        { name: "b", type: "VARCHAR" },
      ],
      referenced: ["a"],
    });
    expect(rows).toEqual([
      { spec: "a", snapshot: "—", status: "dropped" },
      { spec: "—", snapshot: "c, b", status: "added · ignored" },
    ]);
  });

  it("does not give renamed a status of its own — a drop and an extra column stay two rows", () => {
    const rows = driftTable({
      drifted: [{ name: "plan_tier", kind: "dropped", expected: "plan_tier", found: null }],
      snapshot: [{ name: "tier_name", type: "VARCHAR" }],
      referenced: ["plan_tier"],
    });
    expect(rows.map((row) => row.status)).toEqual(["dropped", "added · ignored"]);
    expect(rows.some((row) => row.status === "renamed")).toBe(false);
  });
});

describe("referencedNames", () => {
  it("unions drifted names with the source_schema baseline keys", () => {
    expect(
      referencedNames(
        { x_chartagent: { source_schema: { a: "number", b: "string" } } },
        [DROPPED],
      ),
    ).toEqual(["a", "b"]);
  });

  it("falls back to drifted names when the frame has no baseline", () => {
    expect(referencedNames({ chart_spec: {} }, [DROPPED])).toEqual(["a"]);
  });

  it("includes transform col() names so a referenced snapshot column is not added · ignored", () => {
    expect(
      referencedNames(
        {
          x_chartagent: {
            transform: {
              filter: {
                kind: "and",
                args: [
                  { kind: "col", name: "a" },
                  { kind: "col", name: "b" },
                ],
              },
            },
          },
        },
        [DROPPED],
      ),
    ).toEqual(["a", "b"]);
  });
});
