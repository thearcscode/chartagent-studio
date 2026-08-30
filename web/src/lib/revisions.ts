/** Revision-list helpers (#9). `authored_flint_version` is a recorded
 * fact, never a gate (ADR-0007 D11): the UI may name another pin and
 * must not offer to load it. */

/** Copy shown when a revision was saved under a pin other than the one
 * this app serves. `null` when there is nothing to say — including a
 * recipe, which has no authored pin. */
export function pinNote(authored: string | null, served: string): string | null {
  if (authored === null || authored === served) return null;
  return `Saved under Flint ${authored}`;
}
