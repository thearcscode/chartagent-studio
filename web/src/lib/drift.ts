/** The three-column drift table (#8): what the spec references, what the
 * snapshot has, and a status word driven by `kind`. Additive snapshot
 * columns the spec does not reference show as *added · ignored*. A
 * disappeared referenced column is `dropped` — `"renamed"` is a Literal
 * the library never produces, and this module does not invent it.
 */

import type { SnapshotColumn } from "./charts-api";

export interface DriftedField {
  name: string;
  kind: string;
  expected: string | null;
  found: string | null;
}

export interface DriftRow {
  spec: string;
  snapshot: string;
  status: string;
}

export interface DriftTableInput {
  drifted: DriftedField[];
  snapshot: SnapshotColumn[];
  referenced: string[];
}

/** Referenced source columns: the baseline's keys (what the spec was
 * planned against), every name the failed bind already listed, and
 * `col()` names in the transform so a still-present referenced column
 * is not shown as *added · ignored* when the baseline is missing. */
export function referencedNames(
  content: Record<string, unknown>,
  drifted: DriftedField[],
): string[] {
  const names = new Set<string>(drifted.map((field) => field.name));
  const xc = content.x_chartagent;
  if (typeof xc === "object" && xc !== null) {
    const block = xc as Record<string, unknown>;
    const schema = block.source_schema;
    if (typeof schema === "object" && schema !== null) {
      for (const key of Object.keys(schema)) names.add(key);
    }
    collectColNames(block.transform, names);
  }
  return [...names];
}

function collectColNames(node: unknown, into: Set<string>): void {
  if (Array.isArray(node)) {
    for (const item of node) collectColNames(item, into);
    return;
  }
  if (typeof node !== "object" || node === null) return;
  const obj = node as Record<string, unknown>;
  if (obj.kind === "col" && typeof obj.name === "string") {
    into.add(obj.name);
    return;
  }
  if (Array.isArray(obj.group_by)) {
    for (const name of obj.group_by) {
      if (typeof name === "string") into.add(name);
    }
  }
  for (const value of Object.values(obj)) collectColNames(value, into);
}

export function driftTable({ drifted, snapshot, referenced }: DriftTableInput): DriftRow[] {
  const referencedSet = new Set(referenced);
  const rows: DriftRow[] = drifted.map((field) => ({
    spec: field.name,
    snapshot: field.kind === "retyped" ? field.name : "—",
    status: field.kind,
  }));
  const added = snapshot
    .map((column) => column.name)
    .filter((name) => !referencedSet.has(name));
  if (added.length > 0) {
    rows.push({ spec: "—", snapshot: added.join(", "), status: "added · ignored" });
  }
  return rows;
}

/** The planning baseline's buckets, already computed by the library and
 * stored on the frame. Used to filter candidate columns for a remap. */
export function baselineBuckets(content: Record<string, unknown>): Record<string, string> {
  const xc = content.x_chartagent;
  if (typeof xc !== "object" || xc === null) return {};
  const schema = (xc as Record<string, unknown>).source_schema;
  if (typeof schema !== "object" || schema === null) return {};
  const buckets: Record<string, string> = {};
  for (const [key, value] of Object.entries(schema)) {
    if (typeof value === "string") buckets[key] = value;
  }
  return buckets;
}

/** Candidate columns for a dropped field: matching bucket only. A `BLOB`
 * (`other`) is never offered for a `number` measure. */
export function candidateColumns(
  expectedBucket: string | undefined,
  snapshot: SnapshotColumn[],
): SnapshotColumn[] {
  // No baseline bucket means we cannot match — offering the whole snapshot
  // would include a BLOB for a measure. Filter is closed, not open.
  if (expectedBucket === undefined) return [];
  return snapshot.filter((column) => column.bucket === expectedBucket);
}

export function mappingComplete(
  drifted: DriftedField[],
  mapping: Record<string, string>,
): boolean {
  const dropped = drifted.filter((field) => field.kind === "dropped");
  if (dropped.length === 0) return false;
  return dropped.every((field) => Boolean(mapping[field.name]));
}

export function hasDropped(drifted: DriftedField[]): boolean {
  return drifted.some((field) => field.kind === "dropped");
}

export function hasRetyped(drifted: DriftedField[]): boolean {
  return drifted.some((field) => field.kind === "retyped");
}
