/** Mounts a custom-rail shell in an opaque-origin iframe and shows the paint
 * signal (ADR-0017 D5/D7/D15, channel contract version 1). Knows nothing of
 * fixtures or pages: shell, rows, theme and size in; one `chartagent/paint`
 * per request out; one `chartagent/painted` awaited.
 *
 * The sandbox is the library's tokens joined by a space — and refused unless
 * that is exactly `allow-scripts`. The sender check is `event.source` only;
 * `event.origin` is "null" for every opaque frame. The channel is covered
 * end to end by the Playwright smoke test, not by component tests.
 */

import { useEffect, useRef, useState } from "react";

export interface Shell {
  html: string;
  sandbox: string[];
}

export interface PaintSize {
  width: number;
  height: number;
}

type Signal =
  | { kind: "drawing" }
  | { kind: "painted"; series: number }
  | { kind: "failed"; reason: string };

const CONTRACT_VERSION = 1;
const PAINT_TIMEOUT_MS = 10_000;
const ALLOWED_SANDBOX = "allow-scripts";

interface Props {
  shell: Shell;
  rows: Array<Record<string, unknown>>;
  theme: Record<string, string>;
  size: PaintSize;
  /** Change it to ask for a fresh paint (the contract allows repeats). */
  repaintKey?: string;
}

export function SandboxedPaint({ shell, rows, theme, size, repaintKey }: Props) {
  const sandbox = shell.sandbox.join(" ");
  const refused = sandbox !== ALLOWED_SANDBOX;
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [signal, setSignal] = useState<Signal>(
    refused
      ? { kind: "failed", reason: "The document was not drawn: its sandbox was not the one Studio allows." }
      : { kind: "drawing" },
  );
  const [paints, setPaints] = useState(0);
  const awaiting = useRef(false);
  const themeKey = JSON.stringify(theme);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const frame = frameRef.current;
      if (!awaiting.current || frame === null || event.source !== frame.contentWindow) return;
      const data: unknown = event.data;
      if (typeof data !== "object" || data === null) return;
      const message = data as Record<string, unknown>;
      if (message.type !== "chartagent/painted" || message.contractVersion !== CONTRACT_VERSION) {
        return;
      }
      awaiting.current = false;
      if (message.ok === true) {
        const series = Array.isArray(message.plottedSeries) ? message.plottedSeries.length : 0;
        setSignal({ kind: "painted", series });
        setPaints((n) => n + 1);
      } else {
        setSignal({ kind: "failed", reason: "The document reported that it did not paint." });
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  useEffect(() => {
    const target = frameRef.current?.contentWindow;
    if (refused || !loaded || !target) return;
    awaiting.current = true;
    setSignal({ kind: "drawing" });
    target.postMessage(
      {
        type: "chartagent/paint",
        contractVersion: CONTRACT_VERSION,
        rows,
        theme: JSON.parse(themeKey) as Record<string, string>,
        container: { width: size.width, height: size.height },
      },
      "*",
    );
    const timer = window.setTimeout(() => {
      if (!awaiting.current) return;
      awaiting.current = false;
      setSignal({ kind: "failed", reason: "No answer from the document in time." });
    }, PAINT_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [refused, loaded, rows, themeKey, repaintKey, size.width, size.height]);

  return (
    <div className="sandboxed-paint">
      <p
        className="paint-signal"
        role="status"
        data-signal={signal.kind}
        data-series-count={signal.kind === "painted" ? String(signal.series) : undefined}
        data-paint-count={String(paints)}
      >
        {signal.kind === "drawing" ? "Drawing…" : null}
        {signal.kind === "painted"
          ? `Painted — series the document declared it plotted: ${signal.series}`
          : null}
        {signal.kind === "failed" ? `Did not paint. ${signal.reason}` : null}
      </p>
      <div className="chart-area">
        {refused ? null : (
          <iframe
            ref={frameRef}
            className="paint-frame"
            title="Custom-rail chart"
            srcDoc={shell.html}
            sandbox={sandbox}
            width={size.width}
            height={size.height}
            onLoad={() => setLoaded(true)}
          />
        )}
      </div>
    </div>
  );
}
