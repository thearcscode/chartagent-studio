/** The house backend radiogroup. What a pick *does* is the page's business:
 * the editor binds (ADR-0007 D7's backend_switch), the Library recompiles
 * from the cache (ADR-0007 D6) — the markup is one thing in both places. */

import { BACKEND_LABELS, BACKENDS, type Backend } from "../lib/backends";

interface BackendPickerProps {
  backend: Backend;
  onPick: (backend: Backend) => void;
  isDisabled?: (candidate: Backend) => boolean;
  title?: (candidate: Backend) => string | undefined;
}

export function BackendPicker({
  backend,
  onPick,
  isDisabled,
  title,
}: BackendPickerProps) {
  return (
    <div className="backend-picker" role="radiogroup" aria-label="Backend">
      {BACKENDS.map((candidate) => (
        <button
          key={candidate}
          type="button"
          className={`backend-button${backend === candidate ? " is-active" : ""}`}
          disabled={isDisabled?.(candidate)}
          title={title?.(candidate)}
          onClick={() => onPick(candidate)}
        >
          {BACKEND_LABELS[candidate]}
        </button>
      ))}
    </div>
  );
}
