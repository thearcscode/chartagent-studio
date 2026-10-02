/** A saved custom-rail chart (#41, #42): painted in the same sandboxed mount
 * the fixture page uses, from the cache — opening binds nothing and writes no
 * run. A stale or missing cache is *Refresh to bind*. Refresh (#42) is the
 * same zero-LLM bind as the Flint page's, against the picked source, and
 * repaints in place from the response rows; a failure shows the shared
 * messages and leaves the picture and cache alone. No backend picker, and
 * the request carries no backend: a recipe has none. `theme_spec` is stored, not applied — the paint
 * channel carries Studio's own data palette, exactly as the fixture page's.
 */

import { useAuth, UserButton } from "@clerk/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { DriftPanel } from "../components/DriftPanel";
import { SandboxedPaint } from "../components/SandboxedPaint";
import {
  fetchCacheObject,
  fetchShell,
  listSources,
  savedRecipeRefresh,
  type ChartShell,
  type SourceOut,
  type SpecOut,
} from "../lib/charts-api";
import { cacheObjectMatches, formatBoundAt, pointerState, UNBOUND_COPY } from "../lib/library";
import { refreshFailure, sourceName, type RecipeOpenState, type RefreshFailure } from "../lib/refresh";
import { dataPaletteTheme } from "../lib/palette";
import { CHART_STAGE } from "../lib/stage";
import { getStoredTheme, setTheme, type Theme } from "../theme";

type Rows = Array<Record<string, unknown>>;

type Fetched =
  | { kind: "unbound"; reason: string; shell: ChartShell | null }
  | { kind: "error"; reason: string }
  | { kind: "ready"; shell: ChartShell; rows: Rows };

/** What the last successful refresh painted; it outranks the opened cache. */
interface Refreshed {
  rows: Rows;
  rowCount: number;
  elapsedMs: number;
  boundAt: string;
}

export function RecipeChartPage({ spec }: { spec: SpecOut }) {
  const { getToken } = useAuth();
  const [theme, setThemeState] = useState<Theme>(() => getStoredTheme(localStorage));
  // Tagged with the revision it answers, so a changed spec reads as loading.
  const [fetched, setFetched] = useState<{ revisionId: string; result: Fetched } | null>(null);
  const [sources, setSources] = useState<SourceOut[]>([]);
  const [sourceId, setSourceId] = useState<string | null>(spec.default_source_id);
  const [refreshing, setRefreshing] = useState(false);
  // The instruction box saves and binds once before it navigates here; its
  // plan time and a bind that failed after the save ride in the navigation
  // state. The plan term lasts until the next Refresh, success or not.
  const location = useLocation();
  const opening = location.state as Partial<RecipeOpenState> | null;
  const [planElapsedMs, setPlanElapsedMs] = useState<number | null>(
    () => opening?.planElapsedMs ?? null,
  );
  const [refreshError, setRefreshError] = useState<RefreshFailure | null>(
    () => opening?.refreshFailure ?? null,
  );
  const [refreshed, setRefreshed] = useState<{ revisionId: string; value: Refreshed } | null>(
    null,
  );
  const paletteTheme = useMemo(() => dataPaletteTheme(), []);
  const state = useMemo(() => pointerState(spec), [spec]);

  useEffect(() => {
    let cancelled = false;
    listSources(getToken)
      .then((rows) => {
        if (!cancelled) setSources(rows);
      })
      .catch(() => {
        if (!cancelled) setSources([]);
      });
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  useEffect(() => {
    let cancelled = false;
    const revisionId = spec.revision_id;
    const done = (result: Fetched) => {
      if (!cancelled) setFetched({ revisionId, result });
    };
    const shellRequest = fetchShell(getToken, spec.id);
    if (state.kind !== "fresh") {
      // Nothing to read from the cache, but the shell is ready for the
      // refresh that will bind it.
      shellRequest
        .then((shell) => done({ kind: "unbound", reason: UNBOUND_COPY[state.kind], shell }))
        .catch(() => done({ kind: "unbound", reason: UNBOUND_COPY[state.kind], shell: null }));
      return () => {
        cancelled = true;
      };
    }
    Promise.all([shellRequest, fetchCacheObject(getToken, spec.id)])
      .then(([shell, object]) => {
        if (object === null) {
          done({ kind: "unbound", reason: UNBOUND_COPY.missing, shell });
        } else if (!cacheObjectMatches(state.pointer, object)) {
          done({ kind: "unbound", reason: UNBOUND_COPY.mismatch, shell });
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

  const opened: Fetched | null =
    fetched?.revisionId === spec.revision_id ? fetched.result : null;
  const latest = refreshed?.revisionId === spec.revision_id ? refreshed.value : null;
  const shell = opened !== null && opened.kind !== "error" ? opened.shell : null;
  // A successful refresh repaints over whatever the open found, stale or
  // missing included; only a shell is needed to draw it.
  const load: Fetched | null =
    latest !== null && shell !== null
      ? { kind: "ready", shell, rows: latest.rows }
      : opened;

  const asOf: string | null =
    latest !== null
      ? `${latest.rowCount} rows · ${Math.round(latest.elapsedMs)} ms · as of ${formatBoundAt(latest.boundAt)}`
      : state.kind === "fresh" && opened?.kind === "ready"
        ? planElapsedMs !== null
          ? `${state.pointer.row_count} rows · ${state.pointer.elapsed_ms} ms bind · ${Math.round(planElapsedMs / 1000)} s plan · as of ${formatBoundAt(state.pointer.bound_at)}`
          : `${state.pointer.row_count} rows · ${state.pointer.elapsed_ms} ms · as of ${formatBoundAt(state.pointer.bound_at)}`
        : null;

  const onRefresh = useCallback(async () => {
    if (sourceId === null) return;
    setRefreshError(null);
    setPlanElapsedMs(null);
    setRefreshing(true);
    try {
      const chosen = sourceId !== spec.default_source_id ? sourceId : undefined;
      const out = await savedRecipeRefresh(getToken, spec.id, chosen);
      setRefreshed({
        revisionId: spec.revision_id,
        value: {
          rows: out.rows,
          rowCount: out.row_count,
          elapsedMs: out.elapsed * 1000,
          boundAt: new Date().toISOString(),
        },
      });
    } catch (error) {
      // The picture stays and the cache is untouched server-side.
      setRefreshError(refreshFailure(error));
    } finally {
      setRefreshing(false);
    }
  }, [getToken, sourceId, spec]);

  function toggleTheme() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next, localStorage, document.body);
    setThemeState(next);
  }

  const referenced = useMemo(() => {
    const names = new Set<string>(
      refreshError?.kind === "drift" ? refreshError.drifted.map((field) => field.name) : [],
    );
    const schema = spec.content.source_schema;
    if (typeof schema === "object" && schema !== null) {
      for (const key of Object.keys(schema)) names.add(key);
    }
    return [...names];
  }, [refreshError, spec.content]);

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
        <select
          className="source-select"
          value={sourceId ?? ""}
          onChange={(event) => setSourceId(event.target.value || null)}
          aria-label="Data source"
        >
          <option value="">Pick a source…</option>
          {sources.map((source) => (
            <option key={source.id} value={source.id}>
              {sourceName(source)}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="ghost-button"
          disabled={refreshing || sourceId === null}
          title={sourceId === null ? "Pick a source to refresh against" : undefined}
          onClick={() => void onRefresh()}
        >
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      <section className="stage-pane">
        {refreshError?.kind === "drift" ? (
          <DriftPanel
            message={refreshError.message}
            drifted={refreshError.drifted}
            snapshot={
              sources.find((source) => source.id === sourceId)?.schema_snapshot.columns ?? []
            }
            referenced={referenced}
            baseline={{}}
            onDismiss={() => setRefreshError(null)}
          />
        ) : null}
        {refreshError?.kind === "other" ? (
          <div className="refresh-error" role="alert">
            <strong>Refresh failed — the previous picture is unchanged.</strong>
            {refreshError.lines.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
        ) : null}
        {asOf !== null ? <p className="cost-line">{asOf}</p> : null}
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
