/** The #74 screen: paste a frame, save it, bind it, draw it. The server
 * binds; the browser compiles. Three states — rendered, amber *won't render
 * here*, error — with the chart area empty on every refusal, two warning
 * rails that never merge, and a cost-and-latency line from the bind that
 * produced the picture.
 *
 * Refresh (#75): one click re-binds the saved revision against the source —
 * zero LLM. A successful refresh redraws from the new envelope through the
 * same client path as any bind; a failed refresh that carries `drifted`
 * opens the recovery table (#8) and leaves the previous picture untouched.
 *
 * History (#9): the list marks current from the pointer. Revert repoints
 * and does not bind — the chart area says *Refresh to bind*. Diff (#10)
 * is server-side over canonical_json; the user picks any two revisions.
 */

import { useAuth, UserButton } from "@clerk/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { BackendPicker } from "../components/BackendPicker";
import { DriftPanel } from "../components/DriftPanel";
import { RevisionDiff } from "../components/RevisionDiff";
import { RevisionList } from "../components/RevisionList";
import { referencedNames, type DriftedField } from "../lib/drift";
import {
  ApiError,
  createSpec,
  deleteSource,
  deleteSpec,
  diffRevisions,
  downloadWorkbook,
  getSpec,
  listRevisions,
  listSources,
  previewBind,
  registerUrlSource,
  revertSpec,
  savedBind,
  updateSpec,
  uploadSource,
  type AdvisoryOut,
  type BindResponse,
  type DiffOut,
  type RevisionOut,
  type SourceOut,
  type SpecOut,
} from "../lib/charts-api";
import { BACKEND_LABELS, type Backend } from "../lib/backends";
import { compileEnvelope, compiledSeriesCount } from "../lib/compile";
import { excelGate } from "../lib/excel";
import { BUILT_AGAINST, loadFlint, type FlintGlobal } from "../lib/flint";
import { defaultDiffPair } from "../lib/revisions";
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
  | { kind: "rendered"; pointCount: number; seriesCount: number }
  | { kind: "stale" }
  | { kind: "amber"; reason: string }
  | { kind: "error"; reason: string };

interface ExcelReady {
  officeJs: string;
  rows: Array<Record<string, unknown>>;
}

interface LastBind {
  content: Record<string, unknown>;
  envelope: BindResponse;
  backend: Backend;
}

type RefreshFailure =
  | { kind: "drift"; message: string; drifted: DriftedField[] }
  | { kind: "other"; lines: string[] };

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
      `${field.name}: expected ${field.expected ?? "—"}, found ${field.found ?? "—"} (${field.kind})`,
    );
  }
  if (body.request_id) lines.push(`request id: ${body.request_id}`);
  return lines;
}

/** Any caught value → displayable lines: the mapped error's typed fields
 * when the server sent them, the plain message otherwise. */
function toErrorLines(error: unknown): string[] {
  return error instanceof ApiError
    ? errorLines(error)
    : [error instanceof Error ? error.message : String(error)];
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
  const [excelReady, setExcelReady] = useState<ExcelReady | null>(null);
  const [serverWarnings, setServerWarnings] = useState<AdvisoryOut[]>([]);
  const [compileWarnings, setCompileWarnings] = useState<
    Array<{ code: string; message: string }>
  >([]);
  const [lastBind, setLastBind] = useState<LastBind | null>(null);
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<RefreshFailure | null>(null);
  const [saving, setSaving] = useState(false);
  const [addingSource, setAddingSource] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [revisions, setRevisions] = useState<RevisionOut[] | null>(null);
  const [reverting, setReverting] = useState(false);
  const [diffFrom, setDiffFrom] = useState<number | null>(null);
  const [diffTo, setDiffTo] = useState<number | null>(null);
  const [diff, setDiff] = useState<DiffOut | null>(null);

  const chartRef = useRef<HTMLDivElement>(null);
  const cleanupRef = useRef<DrawCleanup | null>(null);
  const openedRef = useRef<string | null>(null);
  // The editor text as a ref: binds kicked off from the load effect (or any
  // callback captured before the latest keystroke's render) must read the
  // current text, not a stale closure.
  const editorTextRef = useRef("");

  const updateEditorText = useCallback((value: string) => {
    editorTextRef.current = value;
    setEditorText(value);
  }, []);

  /** A saved chart binds the saved revision server-side, so the editor must
   * be showing exactly that revision before any bind goes out. */
  const editorDiffersFrom = useCallback(
    (currentSpec: SpecOut) =>
      editorTextRef.current !== JSON.stringify(currentSpec.content, null, 2),
    [],
  );

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
      const parsed: unknown = JSON.parse(editorTextRef.current);
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
  }, []);

  /** Compile and draw a bound envelope — the client path every bind shares
   * (open, backend switch, refresh): assemble, palette, the row-count
   * honesty guard, then draw or refuse and name the drop. */
  const drawEnvelope = useCallback(
    async (
      envelope: BindResponse,
      targetBackend: Backend,
      boundContent: Record<string, unknown>,
    ) => {
      const bundle = flint ?? (await loadFlint(getToken));
      setFlint(bundle);
      const outcome = compileEnvelope(bundle, envelope, targetBackend);
      setServerWarnings(envelope.warnings);
      if (outcome.kind === "refusal") {
        // Refuse, name the drop, empty chart area — error for the honesty
        // guard, amber for realised capability.
        emptyChartArea();
        setExcelReady(null);
        setLastBind(null);
        setArea({ kind: outcome.tone, reason: outcome.reason });
        return;
      }
      setCompileWarnings(outcome.compileWarnings);
      setLastBind({ content: boundContent, envelope, backend: targetBackend });
      if (targetBackend === "excel") {
        emptyChartArea();
        if (outcome.pointCount === 0) {
          // 353/365 accepted fixtures refuse on zero rows — empty chart
          // area, not a fake workbook.
          setExcelReady(null);
          setArea({
            kind: "amber",
            reason:
              "Excel refuses on zero rows — empty chart area, not a fake workbook.",
          });
          return;
        }
        try {
          const generated = bundle.generateOfficeJs(outcome.option);
          setExcelReady({
            officeJs: generated.code,
            rows: envelope.input.data.values,
          });
          setArea({
            kind: "amber",
            reason:
              `This chart compiles for Excel — ${outcome.pointCount} points from ` +
              `${envelope.row_count} rows, verified. Excel draws in Excel, not ` +
              `in the browser.`,
          });
        } catch (error) {
          setExcelReady(null);
          setArea({
            kind: "amber",
            reason: `This app does not support this chart: ${
              error instanceof Error ? error.message : String(error)
            }`,
          });
        }
        return;
      }
      setExcelReady(null);
      const el = chartRef.current;
      if (!el) return;
      cleanupRef.current = await drawChart(el, targetBackend, outcome.option);
      setArea({
        kind: "rendered",
        pointCount: outcome.pointCount,
        seriesCount: compiledSeriesCount(outcome.option),
      });
    },
    [emptyChartArea, flint, getToken],
  );

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
      if (currentSpec !== null && editorDiffersFrom(currentSpec)) {
        // Binding with a dirty editor would draw the old frame — and a later
        // save would pair the new frame with rows bound from the old one.
        setFormErrors(["Save your edits first — a saved chart binds the saved revision."]);
        return;
      }
      setFormErrors([]);
      setRefreshError(null);
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
        // The frame the server actually bound: the stored revision for a
        // saved chart, the editor text for a preview.
        await drawEnvelope(
          envelope,
          targetBackend,
          currentSpec !== null ? currentSpec.content : frame,
        );
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
    [drawEnvelope, editorDiffersFrom, emptyChartArea, getToken, parseEditor, sourceId],
  );

  /** Zero-LLM refresh (#75): one bind of the saved revision against the
   * chart's source — new bytes, no model, no new revision. The previous
   * picture stays up while binding, and a failed refresh leaves it exactly
   * as it was; only a successful bind redraws (through the same client path
   * as any draw). */
  const onRefresh = useCallback(async () => {
    if (!spec) return;
    if (editorDiffersFrom(spec)) {
      setFormErrors(["Save your edits first — a refresh binds the saved revision."]);
      return;
    }
    setFormErrors([]);
    setRefreshError(null);
    setRefreshing(true);
    try {
      const chosenSource = sourceId !== null && sourceId !== spec.default_source_id;
      const envelope = await savedBind(getToken, spec.id, {
        backend,
        source_id: chosenSource ? sourceId : undefined,
        trigger: "refresh",
      });
      if (chosenSource) {
        // A chosen source became the chart's default server-side.
        setSpec({ ...spec, default_source_id: sourceId });
      }
      await drawEnvelope(envelope, backend, spec.content);
    } catch (error) {
      // The cache is untouched server-side; the picture, rails and cost
      // line stay. SchemaDriftError opens the recovery table rather than
      // a red box of field lines.
      if (error instanceof ApiError && error.body.error === "schema_drift") {
        setRefreshError({
          kind: "drift",
          message: error.body.message ?? "Schema drift",
          drifted: error.body.drifted ?? [],
        });
      } else {
        setRefreshError({ kind: "other", lines: toErrorLines(error) });
      }
    } finally {
      setRefreshing(false);
    }
  }, [backend, drawEnvelope, editorDiffersFrom, getToken, sourceId, spec]);

  const loadRevisions = useCallback(
    async (chartId: string) => {
      try {
        const rows = await listRevisions(getToken, chartId);
        setRevisions(rows);
        const pair = defaultDiffPair(rows);
        if (pair === null) {
          setDiff(null);
          setDiffFrom(null);
          setDiffTo(null);
          return;
        }
        const [from, to] = pair;
        setDiffFrom(from);
        setDiffTo(to);
        setDiff(await diffRevisions(getToken, chartId, from, to));
      } catch (error) {
        setFormErrors(toErrorLines(error));
      }
    },
    [getToken],
  );

  async function onCompare(from: number, to: number) {
    if (!spec) return;
    try {
      const next = await diffRevisions(getToken, spec.id, from, to);
      setDiffFrom(from);
      setDiffTo(to);
      setDiff(next);
    } catch (error) {
      setFormErrors(toErrorLines(error));
    }
  }

  async function onToggleHistory() {
    if (!spec) return;
    if (historyOpen) {
      setHistoryOpen(false);
      return;
    }
    setHistoryOpen(true);
    await loadRevisions(spec.id);
  }

  async function onRevert(revisionNumber: number) {
    if (!spec) return;
    setReverting(true);
    setFormErrors([]);
    try {
      const reverted = await revertSpec(getToken, spec.id, revisionNumber);
      setSpec(reverted);
      setTitle(reverted.title);
      updateEditorText(JSON.stringify(reverted.content, null, 2));
      emptyChartArea();
      setLastBind(null);
      setServerWarnings([]);
      setCompileWarnings([]);
      setExcelReady(null);
      setRefreshError(null);
      setArea({ kind: "stale" });
      await loadRevisions(reverted.id);
    } catch (error) {
      setFormErrors(toErrorLines(error));
    } finally {
      setReverting(false);
    }
  }

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
    let cancelled = false;
    getSpec(getToken, chartId)
      .then((loaded) => {
        if (cancelled) return;
        // Mark opened only after the spec lands. Setting this before the
        // fetch made Strict Mode's remount skip the retry, so a saved
        // chart URL rendered as a blank new chart.
        openedRef.current = chartId;
        setSpec(loaded);
        setTitle(loaded.title);
        updateEditorText(JSON.stringify(loaded.content, null, 2));
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
      updateEditorText(JSON.stringify(saved.content, null, 2));
      if (!spec) {
        navigate(`/charts/${saved.id}`, { replace: true });
      }
      if (historyOpen) {
        await loadRevisions(saved.id);
      }
    } catch (error) {
      setFormErrors(toErrorLines(error));
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
      setFormErrors(toErrorLines(error));
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
      setFormErrors(toErrorLines(error));
    }
  }

  async function onDownloadExcel() {
    if (excelReady === null) return;
    setFormErrors([]);
    try {
      const blob = await downloadWorkbook(getToken, {
        rows: excelReady.rows,
        office_js: excelReady.officeJs,
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${(title.trim() || "chart").replace(/[/\\?%*:|"<>]/g, "-")}.xlsx`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setFormErrors(toErrorLines(error));
    }
  }

  async function onDeleteChart() {
    if (!spec) return;
    if (!window.confirm("Delete this chart? Revisions, runs and the cached bind go with it.")) {
      return;
    }
    setFormErrors([]);
    try {
      await deleteSpec(getToken, spec.id);
      navigate("/", { replace: true });
    } catch (error) {
      setFormErrors(toErrorLines(error));
    }
  }

  async function onDeleteSource() {
    if (!sourceId) return;
    if (!window.confirm("Delete this source? Charts that used it will ask you to pick a source.")) {
      return;
    }
    setFormErrors([]);
    try {
      const removed = sourceId;
      await deleteSource(getToken, removed);
      setSources((rows) => rows.filter((row) => row.id !== removed));
      setSourceId(null);
      if (spec?.default_source_id === removed) {
        setSpec({ ...spec, default_source_id: null, cache: null });
      }
    } catch (error) {
      setFormErrors(toErrorLines(error));
    }
  }

  const working = area.kind === "working";
  // One "a bind is in flight" flag for every control that would start one.
  const busy = working || refreshing || reverting;

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
        {spec ? (
          <button
            type="button"
            className="ghost-button"
            aria-pressed={historyOpen}
            disabled={busy || saving}
            onClick={() => void onToggleHistory()}
          >
            History
          </button>
        ) : null}
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
        <BackendPicker
          backend={backend}
          isDisabled={(candidate) => busy || (candidate === "excel" && !excel.ok)}
          title={(candidate) =>
            candidate === "excel" && !excel.ok ? excel.reason : undefined
          }
          onPick={(candidate) => {
            setBackend(candidate);
            // Switching backend is a view control and a user-initiated
            // bind — never a silent reuse of another backend's picture.
            void runBind(spec ? "backend_switch" : "preview", candidate, spec);
          }}
        />
        <button
          type="button"
          className="primary-button"
          disabled={busy}
          onClick={() => void runBind(spec ? "backend_switch" : "preview", backend, spec)}
        >
          Bind &amp; draw
        </button>
        {spec ? (
          <button
            type="button"
            className="primary-button"
            disabled={busy || !sourceId}
            title={sourceId ? undefined : "Pick a source to refresh against"}
            onClick={() => void onRefresh()}
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        ) : null}
        <button
          type="button"
          className="primary-button"
          disabled={working || saving}
          onClick={() => void onSave()}
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {excelReady ? (
          <button
            type="button"
            className="primary-button"
            disabled={busy}
            onClick={() => void onDownloadExcel()}
          >
            Download .xlsx
          </button>
        ) : null}
        {spec ? (
          <button
            type="button"
            className="ghost-button"
            disabled={busy || saving}
            onClick={() => void onDeleteChart()}
          >
            Delete chart
          </button>
        ) : null}
        {sourceId ? (
          <button
            type="button"
            className="ghost-button"
            disabled={busy}
            onClick={() => void onDeleteSource()}
          >
            Delete source
          </button>
        ) : null}
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
            onChange={(event) => updateEditorText(event.target.value)}
          />
          {formErrors.length > 0 ? (
            <div className="form-errors" role="alert">
              {formErrors.map((line) => (
                <p key={line}>{line}</p>
              ))}
            </div>
          ) : null}
          {historyOpen ? (
            <div className="history-pane">
              <p className="pane-label">Revisions</p>
              {revisions === null ? (
                <p className="muted">Loading history…</p>
              ) : (
                <>
                  <RevisionList
                    revisions={revisions}
                    servedFlintVersion={BUILT_AGAINST.flintVersion}
                    onRevert={(n) => void onRevert(n)}
                    reverting={reverting}
                  />
                  {diffFrom !== null && diffTo !== null ? (
                    <RevisionDiff
                      revisions={revisions}
                      fromRevision={diffFrom}
                      toRevision={diffTo}
                      diff={diff}
                      onCompare={(from, to) => void onCompare(from, to)}
                    />
                  ) : null}
                </>
              )}
            </div>
          ) : null}
        </section>

        <section className="stage-pane">
          {refreshError?.kind === "drift" && spec ? (
            <DriftPanel
              message={refreshError.message}
              drifted={refreshError.drifted}
              snapshot={
                sources.find((source) => source.id === sourceId)?.schema_snapshot
                  .columns ?? []
              }
              referenced={referencedNames(spec.content, refreshError.drifted)}
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
          <div
            className="chart-area"
            data-state={area.kind}
            data-series-count={area.kind === "rendered" ? String(area.seriesCount) : undefined}
          >
            <div ref={chartRef} className="chart-canvas" />
            {area.kind === "idle" ? (
              <p className="area-note">Bind to draw.</p>
            ) : null}
            {area.kind === "working" ? <p className="area-note">Binding…</p> : null}
            {area.kind === "stale" ? (
              <div className="area-note">
                <strong>Refresh to bind</strong>
                <p>
                  The cache predates this revision — a new chart with old rows is a
                  wrong chart.
                </p>
              </div>
            ) : null}
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

          {serverWarnings
            .filter((warning) => warning.code === "retype_unchecked")
            .map((warning) => (
              <p key={warning.code} className="retype-unchecked">
                {warning.message} The retype check is running partially. One save records the source schema baseline.
              </p>
            ))}

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
