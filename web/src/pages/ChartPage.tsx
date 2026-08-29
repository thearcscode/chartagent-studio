/** The #74 screen: paste a frame, save it, bind it, draw it. The server
 * binds; the browser compiles. Three states — rendered, amber *won't render
 * here*, error — with the chart area empty on every refusal, two warning
 * rails that never merge, and a cost-and-latency line from the bind that
 * produced the picture.
 */

import { useAuth, UserButton } from "@clerk/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  ApiError,
  createSpec,
  getSpec,
  listSources,
  previewBind,
  registerUrlSource,
  savedBind,
  updateSpec,
  uploadSource,
  type AdvisoryOut,
  type BindResponse,
  type SourceOut,
  type SpecOut,
} from "../lib/charts-api";
import { BACKEND_LABELS, BACKENDS, type Backend } from "../lib/backends";
import { compileEnvelope } from "../lib/compile";
import { excelGate } from "../lib/excel";
import { loadFlint, type FlintGlobal } from "../lib/flint";
import { drawChart, type DrawCleanup } from "../lib/renderers";
import { getStoredTheme, setTheme, type Theme } from "../theme";

const EDITOR_PLACEHOLDER = `{
  "chart_spec": {
    "chartType": "Bar Chart",
    "encodings": {
      "x": { "field": "category" },
      "y": { "field": "value" }
    }
  }
}`;

type ChartArea =
  | { kind: "idle" }
  | { kind: "working" }
  | { kind: "rendered"; pointCount: number }
  | { kind: "amber"; reason: string }
  | { kind: "error"; reason: string };

interface LastBind {
  content: Record<string, unknown>;
  envelope: BindResponse;
  backend: Backend;
}

function sourceName(source: SourceOut): string {
  if (source.kind === "upload") return source.original_filename ?? "upload";
  const url = source.url ?? "";
  const segment = url.replace(/\/+$/, "").split("/").pop();
  return segment ?? url;
}

/** The mapped error, rendered with its typed fields — the offending key,
 * chart type, backend and pin, never "something went wrong". */
function errorLines(error: ApiError): string[] {
  const body = error.body;
  const lines: string[] = [];
  const headline = body.message ?? body.detail ?? `HTTP ${error.status}`;
  lines.push(headline);
  const fields: string[] = [];
  if (body.kind) fields.push(`kind: ${body.kind}`);
  if (body.keys?.length) fields.push(`offending: ${body.keys.join(", ")}`);
  if (body.chart_type) fields.push(`chart type: ${body.chart_type}`);
  if (body.backend) fields.push(`backend: ${body.backend}`);
  if (body.pin) fields.push(`pin: ${body.pin}`);
  if (body.stage) fields.push(`stage: ${body.stage}`);
  if (body.row_count !== undefined && body.cap !== undefined) {
    fields.push(`${body.row_count} rows over the cap of ${body.cap}`);
  }
  if (fields.length) lines.push(fields.join(" · "));
  for (const field of body.drifted ?? []) {
    lines.push(
      `${field.name}: expected ${field.expected}, found ${field.found} (${field.kind})`,
    );
  }
  if (body.request_id) lines.push(`request id: ${body.request_id}`);
  return lines;
}

export function ChartPage() {
  const { chartId } = useParams();
  const navigate = useNavigate();
  const { getToken } = useAuth();

  const [theme, setThemeState] = useState<Theme>(() => getStoredTheme(localStorage));
  const [spec, setSpec] = useState<SpecOut | null>(null);
  const [editorText, setEditorText] = useState("");
  const [title, setTitle] = useState("");
  const [sources, setSources] = useState<SourceOut[]>([]);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [backend, setBackend] = useState<Backend>("echarts");
  const [flint, setFlint] = useState<FlintGlobal | null>(null);
  const [area, setArea] = useState<ChartArea>({ kind: "idle" });
  const [serverWarnings, setServerWarnings] = useState<AdvisoryOut[]>([]);
  const [compileWarnings, setCompileWarnings] = useState<
    Array<{ code: string; message: string }>
  >([]);
  const [lastBind, setLastBind] = useState<LastBind | null>(null);
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [addingSource, setAddingSource] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");

  const chartRef = useRef<HTMLDivElement>(null);
  const cleanupRef = useRef<DrawCleanup | null>(null);
  const openedRef = useRef<string | null>(null);

  const toggleTheme = useCallback(() => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next, localStorage, document.body);
    setThemeState(next);
  }, [theme]);

  const emptyChartArea = useCallback(() => {
    cleanupRef.current?.();
    cleanupRef.current = null;
    chartRef.current?.replaceChildren();
  }, []);

  const parseEditor = useCallback((): Record<string, unknown> | null => {
    try {
      const parsed: unknown = JSON.parse(editorText);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setFormErrors(["The frame must be a JSON object."]);
        return null;
      }
      setFormErrors([]);
      return parsed as Record<string, unknown>;
    } catch (error) {
      setFormErrors([
        `The frame does not parse: ${error instanceof Error ? error.message : String(error)}`,
      ]);
      return null;
    }
  }, [editorText]);

  const runBind = useCallback(
    async (
      trigger: "open" | "backend_switch" | "preview",
      targetBackend: Backend,
      currentSpec: SpecOut | null,
    ) => {
      const frame = parseEditor();
      if (!frame) return;
      if (!currentSpec && !sourceId) {
        setFormErrors(["Pick a source before binding an unsaved frame."]);
        return;
      }
      if (
        currentSpec !== null &&
        editorText !== JSON.stringify(currentSpec.content, null, 2)
      ) {
        // A saved chart binds the saved revision server-side. Binding with a
        // dirty editor would draw the old frame — and a later save would
        // pair the new frame with rows bound from the old one.
        setFormErrors(["Save your edits first — a saved chart binds the saved revision."]);
        return;
      }
      setFormErrors([]);
      emptyChartArea();
      setArea({ kind: "working" });
      setServerWarnings([]);
      setCompileWarnings([]);
      try {
        const envelope =
          currentSpec !== null
            ? await savedBind(getToken, currentSpec.id, {
                backend: targetBackend,
                trigger: trigger === "preview" ? "open" : trigger,
              })
            : await previewBind(getToken, {
                content: frame,
                source_id: sourceId as string,
                backend: targetBackend,
              });
        const bundle = flint ?? (await loadFlint(getToken));
        setFlint(bundle);
        const outcome = compileEnvelope(bundle, envelope, targetBackend);
        setServerWarnings(envelope.warnings);
        if (outcome.kind === "refusal") {
          // Refuse, name the drop, empty chart area — error for the honesty
          // guard, amber for realised capability.
          setLastBind(null);
          setArea({ kind: outcome.tone, reason: outcome.reason });
          return;
        }
        setCompileWarnings(outcome.compileWarnings);
        // The frame the server actually bound: the stored revision for a
        // saved chart, the editor text for a preview.
        setLastBind({
          content: currentSpec !== null ? currentSpec.content : frame,
          envelope,
          backend: targetBackend,
        });
        if (targetBackend === "excel") {
          // Compiles, verified against the row count — but Excel draws in
          // Excel, not here. Amber: won't render here.
          setArea({
            kind: "amber",
            reason:
              `This chart compiles for Excel — ${outcome.pointCount} points from ` +
              `${envelope.row_count} rows, verified. Excel draws in Excel, not ` +
              `in the browser; the .xlsx writer arrives with a later ticket.`,
          });
          return;
        }
        const el = chartRef.current;
        if (!el) return;
        cleanupRef.current = await drawChart(el, targetBackend, outcome.option);
        setArea({ kind: "rendered", pointCount: outcome.pointCount });
      } catch (error) {
        emptyChartArea();
        if (error instanceof ApiError && error.body.error === "backend_capability") {
          // Realised capability: a valid document this backend cannot draw.
          setArea({ kind: "amber", reason: errorLines(error).join(" — ") });
          return;
        }
        setArea({
          kind: "error",
          reason:
            error instanceof ApiError
              ? errorLines(error).join(" — ")
              : error instanceof Error
                ? error.message
                : String(error),
        });
      }
    },
    [editorText, emptyChartArea, flint, getToken, parseEditor, sourceId],
  );

  // Initial load: sources, the Flint pin (fail loud on mismatch), and — for
  // a saved chart — the spec, then the user-initiated open bind.
  useEffect(() => {
    let cancelled = false;
    listSources(getToken)
      .then((rows) => {
        if (!cancelled) setSources(rows);
      })
      .catch(() => {
        if (!cancelled) setSources([]);
      });
    loadFlint(getToken)
      .then((bundle) => {
        if (!cancelled) setFlint(bundle);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setArea({
            kind: "error",
            reason: error instanceof Error ? error.message : String(error),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  useEffect(() => {
    if (!chartId || openedRef.current === chartId) return;
    openedRef.current = chartId;
    let cancelled = false;
    getSpec(getToken, chartId)
      .then((loaded) => {
        if (cancelled) return;
        setSpec(loaded);
        setTitle(loaded.title);
        setEditorText(JSON.stringify(loaded.content, null, 2));
        setSourceId(loaded.default_source_id);
        // Opening a saved chart is the user-initiated `open` bind.
        void runBind("open", backend, loaded);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setArea({
            kind: "error",
            reason: error instanceof Error ? error.message : String(error),
          });
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chartId, getToken]);

  const parsedFrame = useMemo(() => {
    try {
      return JSON.parse(editorText) as unknown;
    } catch {
      return null;
    }
  }, [editorText]);

  const excel = useMemo(
    () => (flint ? excelGate(parsedFrame, flint.isExcelSupported) : { ok: false as const, reason: "the Flint bundle is still loading" }),
    [flint, parsedFrame],
  );

  async function onSave() {
    const frame = parseEditor();
    if (!frame) return;
    if (!spec && !sourceId) {
      setFormErrors(["Pick a source before saving."]);
      return;
    }
    setSaving(true);
    setFormErrors([]);
    try {
      const bindBlock = lastBind
        ? {
            backend: lastBind.backend,
            content: lastBind.content,
            rows: lastBind.envelope.input.data.values,
            elapsed_ms: Math.round(lastBind.envelope.elapsed * 1000),
            source_schema: lastBind.envelope.source_schema,
          }
        : undefined;
      const saved = spec
        ? await updateSpec(getToken, spec.id, {
            content: frame,
            title,
            source_id: sourceId ?? undefined,
            bind: bindBlock,
          })
        : await createSpec(getToken, {
            content: frame,
            source_id: sourceId as string,
            title: title.trim() === "" ? undefined : title,
            bind: bindBlock,
          });
      setSpec(saved);
      setTitle(saved.title);
      setEditorText(JSON.stringify(saved.content, null, 2));
      if (!spec) {
        navigate(`/charts/${saved.id}`, { replace: true });
      }
    } catch (error) {
      setFormErrors(
        error instanceof ApiError
          ? errorLines(error)
          : [error instanceof Error ? error.message : String(error)],
      );
    } finally {
      setSaving(false);
    }
  }

  async function onUploadFile(file: File) {
    setFormErrors([]);
    try {
      const created = await uploadSource(getToken, file);
      setSources((rows) => [created, ...rows]);
      setSourceId(created.id);
      setAddingSource(false);
    } catch (error) {
      setFormErrors(
        error instanceof ApiError
          ? errorLines(error)
          : [error instanceof Error ? error.message : String(error)],
      );
    }
  }

  async function onRegisterUrl() {
    setFormErrors([]);
    try {
      const created = await registerUrlSource(getToken, urlDraft.trim());
      setSources((rows) => [created, ...rows]);
      setSourceId(created.id);
      setUrlDraft("");
      setAddingSource(false);
    } catch (error) {
      setFormErrors(
        error instanceof ApiError
          ? errorLines(error)
          : [error instanceof Error ? error.message : String(error)],
      );
    }
  }

  const working = area.kind === "working";

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
        <input
          className="title-input"
          value={title}
          placeholder="Leave blank for an automatic title"
          onChange={(event) => setTitle(event.target.value)}
          aria-label="Chart title"
        />
        {spec ? <span className="revision-chip">rev {spec.revision_number}</span> : null}
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
          onClick={() => setAddingSource((open) => !open)}
        >
          Add source
        </button>
        <div className="backend-picker" role="radiogroup" aria-label="Backend">
          {BACKENDS.map((candidate) => {
            const disabled =
              working || (candidate === "excel" && !excel.ok);
            return (
              <button
                key={candidate}
                type="button"
                className={`backend-button${backend === candidate ? " is-active" : ""}`}
                disabled={disabled}
                title={
                  candidate === "excel" && !excel.ok ? excel.reason : undefined
                }
                onClick={() => {
                  setBackend(candidate);
                  // Switching backend is a view control and a user-initiated
                  // bind — never a silent reuse of another backend's picture.
                  void runBind(
                    spec ? "backend_switch" : "preview",
                    candidate,
                    spec,
                  );
                }}
              >
                {BACKEND_LABELS[candidate]}
              </button>
            );
          })}
        </div>
        <button
          type="button"
          className="primary-button"
          disabled={working}
          onClick={() => void runBind(spec ? "backend_switch" : "preview", backend, spec)}
        >
          Bind &amp; draw
        </button>
        <button
          type="button"
          className="primary-button"
          disabled={working || saving}
          onClick={() => void onSave()}
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </div>

      {addingSource ? (
        <div className="add-source-bar">
          <label className="ghost-button file-button">
            Upload CSV or Parquet
            <input
              type="file"
              accept=".csv,.parquet"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void onUploadFile(file);
              }}
            />
          </label>
          <span className="muted">or</span>
          <input
            className="url-input"
            value={urlDraft}
            placeholder="https://example.com/data.csv"
            onChange={(event) => setUrlDraft(event.target.value)}
            aria-label="Source URL"
          />
          <button
            type="button"
            className="ghost-button"
            disabled={urlDraft.trim() === ""}
            onClick={() => void onRegisterUrl()}
          >
            Register URL
          </button>
        </div>
      ) : null}

      <main className="chart-main">
        <section className="editor-pane">
          <label className="pane-label" htmlFor="frame-editor">
            Input frame
          </label>
          <textarea
            id="frame-editor"
            className="frame-editor"
            spellCheck={false}
            value={editorText}
            placeholder={EDITOR_PLACEHOLDER}
            onChange={(event) => setEditorText(event.target.value)}
          />
          {formErrors.length > 0 ? (
            <div className="form-errors" role="alert">
              {formErrors.map((line) => (
                <p key={line}>{line}</p>
              ))}
            </div>
          ) : null}
        </section>

        <section className="stage-pane">
          <div className="chart-area" data-state={area.kind}>
            <div ref={chartRef} className="chart-canvas" />
            {area.kind === "idle" ? (
              <p className="area-note">Bind to draw.</p>
            ) : null}
            {area.kind === "working" ? <p className="area-note">Binding…</p> : null}
            {area.kind === "amber" ? (
              <div className="area-note amber-note">
                <strong>Won’t render here.</strong>
                <p>{area.reason}</p>
              </div>
            ) : null}
            {area.kind === "error" ? (
              <div className="area-note error-note">
                <strong>Refused.</strong>
                <p>{area.reason}</p>
              </div>
            ) : null}
          </div>

          <div className="rails">
            <aside className="warn-rail" aria-label="Server advisories">
              <span className="rail-badge">SERVER</span>
              {serverWarnings.length === 0 ? (
                <span className="rail-empty">—</span>
              ) : (
                serverWarnings.map((warning) => (
                  <span key={warning.code} className="rail-item" title={warning.message}>
                    {warning.code}
                  </span>
                ))
              )}
            </aside>
            <aside className="warn-rail" aria-label="Compile warnings">
              <span className="rail-badge">COMPILE</span>
              {compileWarnings.length === 0 ? (
                <span className="rail-empty">—</span>
              ) : (
                compileWarnings.map((warning) => (
                  <span key={warning.code} className="rail-item" title={warning.message}>
                    {warning.code}
                  </span>
                ))
              )}
            </aside>
          </div>

          <p className="cost-line">
            {lastBind
              ? `${lastBind.envelope.row_count} rows · ${Math.round(
                  lastBind.envelope.elapsed * 1000,
                )} ms · ${BACKEND_LABELS[lastBind.backend]}`
              : "Not bound yet."}
          </p>
        </section>
      </main>
    </div>
  );
}
