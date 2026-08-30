/** Drift recovery (#8 + #11): what moved, remap each dropped field, then
 * the patch for approval. A retype is named and not remapped — the two
 * working paths are `raw_sql` in the JSON drawer, or fix the data.
 * Regenerating is absent: there is no planner to press it.
 */

import { useState } from "react";

import type { DiffOut, SnapshotColumn } from "../lib/charts-api";
import { HunkList } from "./HunkList";
import {
  candidateColumns,
  driftTable,
  hasDropped,
  hasRetyped,
  mappingComplete,
  type DriftedField,
} from "../lib/drift";

interface DriftPanelProps {
  message: string;
  drifted: DriftedField[];
  snapshot: SnapshotColumn[];
  referenced: string[];
  baseline: Record<string, string>;
  onPreview: (
    mapping: Record<string, string>,
  ) => Promise<DiffOut & { content: Record<string, unknown> }>;
  onApprove: (content: Record<string, unknown>) => Promise<void>;
  onDismiss: () => void;
}

type Phase = "moved" | "remap" | "patch";

const RETYPE_PATHS =
  "A retype cannot be remapped — the transform menu has no cast. Rewrite the transform as raw_sql in the JSON drawer, or fix the data.";

export function DriftPanel({
  message,
  drifted,
  snapshot,
  referenced,
  baseline,
  onPreview,
  onApprove,
  onDismiss,
}: DriftPanelProps) {
  const [phase, setPhase] = useState<Phase>("moved");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [patch, setPatch] = useState<(DiffOut & { content: Record<string, unknown> }) | null>(
    null,
  );
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rows = driftTable({ drifted, snapshot, referenced });
  const dropped = drifted.filter((field) => field.kind === "dropped");
  const ready = mappingComplete(drifted, mapping);
  const stepLabel =
    phase === "moved" ? "1 / 3 · detected" : phase === "remap" ? "2 / 3 · remapping" : "3 / 3 · patch";

  async function preview() {
    if (!ready) return;
    setWorking(true);
    setError(null);
    try {
      const next = await onPreview(mapping);
      setPatch(next);
      setPhase("patch");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setWorking(false);
    }
  }

  async function approve() {
    if (patch === null) return;
    setWorking(true);
    setError(null);
    try {
      await onApprove(patch.content);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="drift-panel" role="alert">
      <div className="drift-banner">
        <div className="drift-banner-head">
          <span className="drift-code">SchemaDriftError</span>
          <span className="drift-cost">raised before rendering · 0 tokens</span>
        </div>
        <p className="drift-message">{message}</p>
      </div>
      <p className="drift-step">{stepLabel}</p>

      {phase === "moved" ? (
        <>
          <table className="drift-table">
            <thead>
              <tr>
                <th>Spec references</th>
                <th>Snapshot has</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.spec}:${row.snapshot}:${row.status}`}>
                  <td>{row.spec}</td>
                  <td>{row.snapshot}</td>
                  <td data-status={row.status}>{row.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="drift-claim">Nothing was rendered and no model was called.</p>
          {hasRetyped(drifted) ? <p className="drift-retype">{RETYPE_PATHS}</p> : null}
        </>
      ) : null}

      {phase === "remap" ? (
        <>
          <p className="drift-claim">Point each dropped field at a column in the new snapshot.</p>
          {dropped.map((field) => {
            const candidates = candidateColumns(baseline[field.name], snapshot);
            return (
              <label key={field.name} className="drift-remap-row">
                <span className="drift-remap-name">{field.name}</span>
                <span className="drift-remap-arrow">→</span>
                <select
                  className="drift-remap-select"
                  aria-label={`Remap ${field.name}`}
                  value={mapping[field.name] ?? ""}
                  onChange={(event) =>
                    setMapping((current) => ({ ...current, [field.name]: event.target.value }))
                  }
                >
                  <option value="">Pick a column…</option>
                  {candidates.map((column) => (
                    <option key={column.name} value={column.name}>
                      {column.name}
                    </option>
                  ))}
                </select>
              </label>
            );
          })}
          {hasRetyped(drifted) ? <p className="drift-retype">{RETYPE_PATHS}</p> : null}
        </>
      ) : null}

      {phase === "patch" && patch !== null ? (
        <div className="drift-patch">
          <p className="drift-patch-cost">
            spec patch · {patch.hunks.length}{" "}
            {patch.hunks.length === 1 ? "hunk" : "hunks"} · no model call
          </p>
          <HunkList hunks={patch.hunks} />
        </div>
      ) : null}

      {error ? (
        <p className="drift-error" role="status">
          {error}
        </p>
      ) : null}

      <div className="drift-actions">
        <button type="button" className="ghost-button" onClick={onDismiss} disabled={working}>
          Leave as is
        </button>
        {phase === "moved" && hasDropped(drifted) ? (
          <button
            type="button"
            className="primary-button"
            onClick={() => setPhase("remap")}
            disabled={working}
          >
            Remap dropped columns
          </button>
        ) : null}
        {phase === "remap" ? (
          <button
            type="button"
            className="primary-button"
            onClick={() => void preview()}
            disabled={working || !ready}
          >
            {working ? "Previewing…" : "Preview patch"}
          </button>
        ) : null}
        {phase === "patch" ? (
          <button
            type="button"
            className="primary-button"
            onClick={() => void approve()}
            disabled={working}
          >
            {working ? "Saving…" : "Approve and save"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
