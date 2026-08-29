/** A Library card (#76): a saved chart rendered from its cached bind. The
 * card binds nothing — a fresh pointer reads the cache object and compiles
 * it in the browser against the current UI switch's backend; a stale
 * pointer, a missing object, or a guard-key mismatch is *Refresh to bind*.
 * The envelope is reconstructed locally (ADR-0007 D6): the served bundle's
 * flint_version, the switch's backend, the current revision's frame, the
 * cache's rows. A backend switch recompiles the same rows — it never
 * re-fetches and never re-reads a source.
 *
 * The card area is derived, not stored: the pointer comparison, the cache
 * read and the compile are pure or async-callback state, and the only
 * effect that touches the DOM is the draw — which empties the area first,
 * so no refusal ever leaves a partial render.
 */

import { useAuth } from "@clerk/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { BACKEND_LABELS, type Backend } from "../lib/backends";
import { fetchCacheObject, type SpecOut } from "../lib/charts-api";
import { compileEnvelope } from "../lib/compile";
import { excelGate } from "../lib/excel";
import { BUILT_AGAINST, type FlintGlobal } from "../lib/flint";
import {
  cacheObjectMatches,
  envelopeFromCache,
  formatBoundAt,
  pointerState,
} from "../lib/library";
import { drawChart, type DrawCleanup } from "../lib/renderers";

type Unbound = { kind: "unbound"; reason: string };

type CardArea =
  | { kind: "loading" }
  | Unbound
  | { kind: "rendered" }
  | { kind: "amber"; reason: string }
  | { kind: "error"; reason: string };

/** The cache read, keyed by the revision it was read for — a read that
 * comes back against a pointer the card no longer holds is not used. */
type CacheRead =
  | { kind: "loading" }
  | Unbound
  | { kind: "ready"; revisionId: string; rows: Array<Record<string, unknown>> };

const UNBOUND_COPY = {
  none: "Never bound.",
  stale:
    "The cache predates this revision or its source — a new chart with old rows is a wrong chart.",
  missing: "The cached object is gone.",
  mismatch: "The cached object names another revision — a wrong chart, not an early one.",
} as const;

export function LibraryCard({
  card,
  backend,
  flint,
}: {
  card: SpecOut;
  backend: Backend;
  flint: FlintGlobal;
}) {
  const { getToken } = useAuth();
  const state = useMemo(() => pointerState(card), [card]);
  const [read, setRead] = useState<CacheRead>({ kind: "loading" });
  const canvasRef = useRef<HTMLDivElement>(null);
  const cleanupRef = useRef<DrawCleanup | null>(null);

  // The cache read — only ever on a fresh pointer. No card load ever binds.
  useEffect(() => {
    if (state.kind !== "fresh") return;
    let cancelled = false;
    const pointer = state.pointer;
    fetchCacheObject(getToken, card.id)
      .then((object) => {
        if (cancelled) return;
        if (object === null) {
          setRead({ kind: "unbound", reason: UNBOUND_COPY.missing });
          return;
        }
        // The slot is overwritten in place: a revision_id disagreement is a
        // wrong chart, not a display that is merely early — discard.
        if (!cacheObjectMatches(pointer, object)) {
          setRead({ kind: "unbound", reason: UNBOUND_COPY.mismatch });
          return;
        }
        setRead({ kind: "ready", revisionId: object.revision_id, rows: object.rows });
      })
      .catch(() => {
        if (!cancelled) {
          setRead({ kind: "unbound", reason: UNBOUND_COPY.missing });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [card, state, getToken]);

  // The rows for the current pointer — a read that predates a card change
  // is not drawn against the new frame.
  const rows =
    state.kind === "fresh" &&
    read.kind === "ready" &&
    read.revisionId === state.pointer.revision_id
      ? read.rows
      : null;

  // The compile is pure: derive the outcome. A backend switch lands here
  // and recompiles the same rows — no refetch, no bind. Excel is the two
  // honest states it always was: gated before compile, amber after it —
  // and the early return narrows the backend the draw variant carries.
  const compiled = useMemo(() => {
    if (state.kind !== "fresh" || rows === null) return null;
    if (backend === "excel") {
      const gate = excelGate(card.content, flint.isExcelSupported);
      if (!gate.ok) return { kind: "amber" as const, reason: gate.reason };
    }
    const envelope = envelopeFromCache(
      card,
      state.pointer,
      rows,
      BUILT_AGAINST.flintVersion,
      backend,
    );
    const outcome = compileEnvelope(flint, envelope, backend);
    if (outcome.kind === "refusal") {
      return { kind: outcome.tone, reason: outcome.reason } as const;
    }
    if (backend === "excel") {
      // Compiles, verified against the row count — but Excel draws in
      // Excel, not here.
      return {
        kind: "amber" as const,
        reason:
          `This chart compiles for Excel — ${outcome.pointCount} points from ` +
          `${envelope.row_count} rows, verified. Excel draws in Excel, not here.`,
      };
    }
    return { kind: "draw" as const, option: outcome.option, backend };
  }, [card, state, rows, backend, flint]);

  const area: CardArea =
    state.kind !== "fresh"
      ? { kind: "unbound", reason: UNBOUND_COPY[state.kind] }
      : read.kind === "unbound"
        ? read
        : compiled === null
          ? { kind: "loading" }
          : compiled.kind === "draw"
            ? { kind: "rendered" }
            : compiled;

  // The draw — the one effect that touches the chart DOM. It empties the
  // area on every transition first: no partial render, no stale picture
  // beside a *Refresh to bind*.
  useEffect(() => {
    cleanupRef.current?.();
    cleanupRef.current = null;
    canvasRef.current?.replaceChildren();
    if (compiled?.kind !== "draw") return;
    const el = canvasRef.current;
    if (!el) return;
    let cancelled = false;
    void (async () => {
      const cleanup = await drawChart(el, compiled.backend, compiled.option);
      if (cancelled) {
        cleanup();
        return;
      }
      cleanupRef.current = cleanup;
    })();
    return () => {
      cancelled = true;
    };
  }, [compiled]);

  // Empty the chart area when the card goes away.
  useEffect(
    () => () => {
      cleanupRef.current?.();
      cleanupRef.current = null;
    },
    [],
  );

  const pointer = state.kind === "fresh" ? state.pointer : null;

  return (
    <article className="library-card" data-state={area.kind}>
      <header className="card-header">
        <h2 className="card-title">
          <Link to={`/charts/${card.id}`} className="card-title-link">
            {card.title}
          </Link>
        </h2>
        <span className="revision-chip">rev {card.revision_number}</span>
      </header>
      <div className="card-chart-area">
        <div ref={canvasRef} className="chart-canvas" />
        {area.kind === "loading" ? (
          <p className="area-note">Reading the cached bind…</p>
        ) : null}
        {area.kind === "unbound" ? (
          <div className="area-note">
            <p>{area.reason}</p>
            <p>
              <Link to={`/charts/${card.id}`} className="ghost-button">
                Refresh to bind
              </Link>
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
      {pointer !== null && area.kind !== "unbound" ? (
        <p className="cost-line">
          {pointer.row_count} rows · {pointer.elapsed_ms} ms ·{" "}
          {BACKEND_LABELS[backend]}
          {pointer.source_kind === "url"
            ? ` · as of ${formatBoundAt(pointer.bound_at)}`
            : ""}
        </p>
      ) : null}
    </article>
  );
}
