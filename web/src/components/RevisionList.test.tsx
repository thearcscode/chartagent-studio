/** The history list (#9): newest-first rows, current from the pointer
 * (never from the highest number), the authored pin displayed and never
 * offered as a bundle to load, revert on every row that is not current.
 *
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RevisionOut } from "../lib/charts-api";
import { RevisionList } from "./RevisionList";

afterEach(cleanup);

const SERVED = "0.5.1";

function rev(
  number: number,
  overrides: Partial<RevisionOut> = {},
): RevisionOut {
  return {
    revision_number: number,
    created_at: `2026-08-30T12:0${number}:00Z`,
    content_hash: `hash-${number}`,
    authored_flint_version: SERVED,
    current: false,
    ...overrides,
  };
}

describe("RevisionList", () => {
  it("marks current from the pointer, not the highest number", () => {
    render(
      <RevisionList
        revisions={[rev(2), rev(1, { current: true })]}
        servedFlintVersion={SERVED}
        onRevert={() => {}}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows[0].textContent).toMatch(/rev 2/);
    expect(rows[0].textContent).not.toMatch(/current/);
    expect(rows[1].textContent).toMatch(/rev 1/);
    expect(rows[1].textContent).toMatch(/current/);
    // Revert is on the non-current row only.
    expect(screen.getByRole("button", { name: "Revert to revision 2" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Revert to revision 1" })).toBeNull();
  });

  it("names a revision saved under another pin and does not offer to load that Flint", () => {
    render(
      <RevisionList
        revisions={[rev(1, { current: true, authored_flint_version: "0.2.1" })]}
        servedFlintVersion={SERVED}
        onRevert={() => {}}
      />,
    );
    expect(screen.getByText("Saved under Flint 0.2.1")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /load/i })).toBeNull();
    expect(screen.queryByRole("link", { name: /flint/i })).toBeNull();
  });

  it("calls onRevert with the revision number", () => {
    const onRevert = vi.fn();
    render(
      <RevisionList
        revisions={[rev(2, { current: true }), rev(1)]}
        servedFlintVersion={SERVED}
        onRevert={onRevert}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Revert to revision 1" }));
    expect(onRevert).toHaveBeenCalledWith(1);
  });
});
