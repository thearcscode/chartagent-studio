/** A saved custom-rail chart (#41): painted in the same sandboxed mount the
 * fixture page uses, from the cache — opening binds nothing and writes no
 * run. A stale or missing cache is *Refresh to bind*. No backend picker: a
 * recipe has no backend. `theme_spec` is stored, not applied — the paint
 * channel carries Studio's own data palette, exactly as the fixture page's.
 */

import { useAuth, UserButton } from "@clerk/react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { SandboxedPaint } from "../components/SandboxedPaint";
import {
  fetchCacheObject,
  fetchShell,
  type ChartShell,
  type SpecOut,
} from "../lib/charts-api";
import { cacheObjectMatches, pointerState, UNBOUND_COPY } from "../lib/library";
import { dataPaletteTheme } from "../lib/palette";
import { CHART_STAGE } from "../lib/stage";
import { getStoredTheme, setTheme, type Theme } from "../theme";

type Fetched =
  | { kind: "unbound"; reason: string }
  | { kind: "error"; reason: string }
  | { kind: "ready"; shell: ChartShell; rows: Array<Record<string, unknown>> };

export function RecipeChartPage({ spec }: { spec: SpecOut }) {
  const { getToken } = useAuth();
  const [theme, setThemeState] = useState<Theme>(() => getStoredTheme(localStorage));
  // Tagged with the revision it answers, so a changed spec reads as loading.
  const [fetched, setFetched] = useState<{ revisionId: string; result: Fetched } | null>(null);
  const paletteTheme = useMemo(() => dataPaletteTheme(), []);
  const state = useMemo(() => pointerState(spec), [spec]);

  useEffect(() => {
    if (state.kind !== "fresh") return;
    let cancelled = false;
    const revisionId = spec.revision_id;
    const done = (result: Fetched) => {
      if (!cancelled) setFetched({ revisionId, result });
    };
    Promise.all([fetchShell(getToken, spec.id), fetchCacheObject(getToken, spec.id)])
      .then(([shell, object]) => {
        if (object === null) {
          done({ kind: "unbound", reason: UNBOUND_COPY.missing });
        } else if (!cacheObjectMatches(state.pointer, object)) {
          done({ kind: "unbound", reason: UNBOUND_COPY.mismatch });
        } else {
          done({ kind: "ready", shell, rows: object.rows });
        }
      })
      .catch((error: unknown) => {
        done({ kind: "error", reason: error instanceof Error ? error.message : String(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [spec, state, getToken]);

  const load: Fetched | null =
    state.kind !== "fresh"
      ? { kind: "unbound", reason: UNBOUND_COPY[state.kind] }
      : fetched?.revisionId === spec.revision_id
        ? fetched.result
        : null;

  function toggleTheme() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next, localStorage, document.body);
    setThemeState(next);
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="wordmark">
          <Link to="/" className="wordmark-link">
            Chartagent Studio
          </Link>
        </span>
        <div className="header-actions">
          <button type="button" className="ghost-button" onClick={toggleTheme}>
            {theme === "dark" ? "Light" : "Dark"} theme
          </button>
          <UserButton />
        </div>
      </header>
      <div className="chart-toolbar">
        <h1 className="chart-title">{spec.title}</h1>
        <span className="revision-chip">rev {spec.revision_number}</span>
      </div>
      <section className="stage-pane">
        {load === null ? (
          <p className="paint-signal" role="status" data-signal="drawing">
            Loading…
          </p>
        ) : null}
        {load?.kind === "unbound" ? (
          <div className="area-note" data-state="unbound">
            <p>{load.reason}</p>
            <p>Refresh to bind</p>
          </div>
        ) : null}
        {load?.kind === "error" ? (
          <p className="paint-signal" role="alert" data-signal="failed">
            Did not load the chart. {load.reason}
          </p>
        ) : null}
        {load?.kind === "ready" ? (
          <SandboxedPaint
            shell={load.shell}
            rows={load.rows}
            theme={paletteTheme}
            repaintKey={theme}
            size={CHART_STAGE}
          />
        ) : null}
      </section>
    </div>
  );
}
