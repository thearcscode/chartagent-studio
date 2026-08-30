/** Step 1 of drift recovery (#8): what moved. The three-column table,
 * the $0.00 claim on the screen at the moment it is true, and nothing
 * else — remap, patch, regenerate, schedule and review are later tickets
 * or out of v0. Abandoning is "Leave as is": the chart is not written.
 */

import type { SnapshotColumn } from "../lib/charts-api";
import { driftTable, type DriftedField } from "../lib/drift";

interface DriftPanelProps {
  message: string;
  drifted: DriftedField[];
  snapshot: SnapshotColumn[];
  referenced: string[];
  onDismiss: () => void;
}

export function DriftPanel({
  message,
  drifted,
  snapshot,
  referenced,
  onDismiss,
}: DriftPanelProps) {
  const rows = driftTable({ drifted, snapshot, referenced });
  return (
    <div className="drift-panel" role="alert">
      <div className="drift-banner">
        <div className="drift-banner-head">
          <span className="drift-code">SchemaDriftError</span>
          <span className="drift-cost">raised before rendering · 0 tokens</span>
        </div>
        <p className="drift-message">{message}</p>
      </div>
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
      <div className="drift-actions">
        <button type="button" className="ghost-button" onClick={onDismiss}>
          Leave as is
        </button>
      </div>
    </div>
  );
}
