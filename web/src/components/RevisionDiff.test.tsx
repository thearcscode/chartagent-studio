/** The history-screen diff (#10): pick any two revisions, see structural
 * hunks, and label a source-schema-only change.
 *
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DiffOut, RevisionOut } from "../lib/charts-api";
import { RevisionDiff } from "./RevisionDiff";

afterEach(cleanup);

function rev(number: number, current = false): RevisionOut {
  return {
    revision_number: number,
    created_at: `2026-08-30T12:0${number}:00Z`,
    content_hash: `hash-${number}`,
    authored_flint_version: "0.5.1",
    current,
  };
}

const REVISIONS = [rev(2, true), rev(1)];

const FIELD_DIFF: DiffOut = {
  from_revision: 1,
  to_revision: 2,
  source_schema_only: false,
  hunks: [
    {
      op: "changed",
      path: "/chart_spec/encodings/x/field",
      from_value: "b",
      to_value: "a",
    },
  ],
};

describe("RevisionDiff", () => {
  it("shows the changed path and both values", () => {
    render(
      <RevisionDiff
        revisions={REVISIONS}
        fromRevision={1}
        toRevision={2}
        diff={FIELD_DIFF}
        onCompare={() => {}}
      />,
    );
    expect(screen.getByText("1 hunk")).toBeTruthy();
    expect(screen.getByText("/chart_spec/encodings/x/field")).toBeTruthy();
    expect(screen.getByText('− "b"')).toBeTruthy();
    expect(screen.getByText('+ "a"')).toBeTruthy();
    expect(screen.queryByText("source-schema-only change")).toBeNull();
  });

  it("labels a source-schema-only change", () => {
    render(
      <RevisionDiff
        revisions={REVISIONS}
        fromRevision={1}
        toRevision={2}
        diff={{
          from_revision: 1,
          to_revision: 2,
          source_schema_only: true,
          hunks: [
            {
              op: "added",
              path: "/x_chartagent/source_schema",
              from_value: null,
              to_value: { a: "number" },
            },
          ],
        }}
        onCompare={() => {}}
      />,
    );
    expect(screen.getByText("source-schema-only change")).toBeTruthy();
    expect(screen.getByText("/x_chartagent/source_schema")).toBeTruthy();
  });

  it("says zero hunks when a revision is compared with itself", () => {
    render(
      <RevisionDiff
        revisions={[rev(1, true)]}
        fromRevision={1}
        toRevision={1}
        diff={{
          from_revision: 1,
          to_revision: 1,
          source_schema_only: false,
          hunks: [],
        }}
        onCompare={() => {}}
      />,
    );
    expect(screen.getByText("0 hunks")).toBeTruthy();
    expect(screen.getByText("Identical revisions — zero hunks.")).toBeTruthy();
  });

  it("calls onCompare when the user picks another revision", () => {
    const onCompare = vi.fn();
    render(
      <RevisionDiff
        revisions={REVISIONS}
        fromRevision={1}
        toRevision={2}
        diff={FIELD_DIFF}
        onCompare={onCompare}
      />,
    );
    fireEvent.change(screen.getByLabelText("Diff from revision"), {
      target: { value: "2" },
    });
    expect(onCompare).toHaveBeenCalledWith(2, 2);
  });
});
