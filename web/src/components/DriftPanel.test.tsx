/** Remap gating and candidate filtering (#11): an unmapped dropped field
 * blocks the patch, and a number field is never offered a BLOB.
 *
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DriftPanel } from "./DriftPanel";

afterEach(cleanup);

const SNAPSHOT = [
  { name: "revenue", type: "BIGINT", bucket: "number" },
  { name: "payload", type: "BLOB", bucket: "other" },
  { name: "label", type: "VARCHAR", bucket: "string" },
];

const DROPPED = [{ name: "amount", kind: "dropped", expected: "amount", found: null }];

describe("DriftPanel remap", () => {
  it("offers a dropped number field only number columns and never a BLOB", () => {
    render(
      <DriftPanel
        message="source column(s) dropped: amount"
        drifted={DROPPED}
        snapshot={SNAPSHOT}
        referenced={["amount"]}
        baseline={{ amount: "number" }}
        onPreview={vi.fn()}
        onApprove={vi.fn()}
        onDismiss={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Remap dropped columns" }));
    const select = screen.getByRole("combobox", { name: "Remap amount" }) as HTMLSelectElement;
    const labels = [...select.options].map((option) => option.text);
    expect(labels).toContain("revenue");
    expect(labels).not.toContain("payload");
    expect(labels).not.toContain("BLOB");
  });

  it("blocks the patch step while a dropped field is unmapped", () => {
    render(
      <DriftPanel
        message="source column(s) dropped: amount"
        drifted={DROPPED}
        snapshot={SNAPSHOT}
        referenced={["amount"]}
        baseline={{ amount: "number" }}
        onPreview={vi.fn()}
        onApprove={vi.fn()}
        onDismiss={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Remap dropped columns" }));
    expect((screen.getByRole("button", { name: "Preview patch" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Remap amount" }), {
      target: { value: "revenue" },
    });
    expect((screen.getByRole("button", { name: "Preview patch" }) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it("names a retype and does not offer a remap", () => {
    render(
      <DriftPanel
        message="bucket number → string on churn_rate"
        drifted={[{ name: "churn_rate", kind: "retyped", expected: "number", found: "string" }]}
        snapshot={[{ name: "churn_rate", type: "VARCHAR", bucket: "string" }]}
        referenced={["churn_rate"]}
        baseline={{ churn_rate: "number" }}
        onPreview={vi.fn()}
        onApprove={vi.fn()}
        onDismiss={() => {}}
      />,
    );
    expect(screen.getByText("retyped")).toBeTruthy();
    expect(screen.getByText(/raw_sql/)).toBeTruthy();
    expect(screen.getByText(/fix the data/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /remap/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /regenerate/i })).toBeNull();
  });
});
