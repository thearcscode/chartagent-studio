/** The three-column drift table (#8): what the spec references, what the
 * snapshot has, and a status word driven by `kind`. Additive snapshot
 * columns the spec does not reference show as *added · ignored*. A
 * disappeared referenced column is `dropped` — `"renamed"` is a Literal
 * the library never produces, and this module does not invent it.
 */

export interface DriftedField {
  name: string;
  kind: string;
  expected: string | null;
  found: string | null;
}

export interface SnapshotColumn {
  name: string;
  type: string;
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

function statusWord(kind: string): string {
  if (kind === "retyped") return "retyped";
  return "dropped";
}

export function driftTable({ drifted, snapshot, referenced }: DriftTableInput): DriftRow[] {
  const referencedSet = new Set(referenced);
  const rows: DriftRow[] = drifted.map((field) => ({
    spec: field.name,
    snapshot: field.kind === "retyped" ? field.name : "—",
    status: statusWord(field.kind),
  }));
  const added = snapshot
    .map((column) => column.name)
    .filter((name) => !referencedSet.has(name));
  if (added.length > 0) {
    rows.push({ spec: "—", snapshot: added.join(", "), status: "added · ignored" });
  }
  return rows;
}
