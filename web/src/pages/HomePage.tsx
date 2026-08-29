/** The Library (#76): saved charts as live cards, each rendered from its
 * cached bind — the page itself is the refresh claim. Opening it binds
 * nothing: six cards are six cache reads, zero DuckDB scans, zero run
 * rows. A card whose pointer is stale says *Refresh to bind* rather than
 * binding silently behind the page load. The backend switch is a view
 * control over the cached rows — it recompiles in the browser and never
 * re-reads a source (ADR-0007 D6).
 */

import { useAuth, UserButton } from "@clerk/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { BackendPicker } from "../components/BackendPicker";
import { LibraryCard } from "../components/LibraryCard";
import type { Backend } from "../lib/backends";
import { listSpecs, type SpecOut } from "../lib/charts-api";
import { loadFlint, type FlintGlobal } from "../lib/flint";
import { getStoredTheme, setTheme, type Theme } from "../theme";

export function HomePage() {
  const { getToken } = useAuth();
  const [theme, setThemeState] = useState<Theme>(() =>
    getStoredTheme(localStorage),
  );
  const [cards, setCards] = useState<SpecOut[] | null>(null);
  const [flint, setFlint] = useState<FlintGlobal | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [backend, setBackend] = useState<Backend>("echarts");

  useEffect(() => {
    let cancelled = false;
    const fail = (error: unknown) => {
      if (!cancelled) {
        setLoadError(error instanceof Error ? error.message : String(error));
      }
    };
    listSpecs(getToken)
      .then((rows) => {
        if (!cancelled) setCards(rows);
      })
      .catch(fail);
    loadFlint(getToken)
      .then((bundle) => {
        if (!cancelled) setFlint(bundle);
      })
      .catch(fail);
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  function toggleTheme() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next, localStorage, document.body);
    setThemeState(next);
  }

  const hasCards = cards !== null && cards.length > 0;
  const loading = (
    <section className="empty-state">
      <h1>Loading…</h1>
    </section>
  );

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="wordmark">Chartagent Studio</span>
        <div className="header-actions">
          <button type="button" className="ghost-button" onClick={toggleTheme}>
            {theme === "dark" ? "Light" : "Dark"} theme
          </button>
          <UserButton />
        </div>
      </header>

      {hasCards ? (
        <div className="chart-toolbar">
          <Link to="/charts/new" className="ghost-button">
            New chart
          </Link>
          <BackendPicker backend={backend} onPick={setBackend} />
          <span className="muted">
            Cards render from the cached bind — switching backend recompiles,
            it never re-reads a source.
          </span>
        </div>
      ) : null}

      <main className={hasCards ? "library-main" : "app-main"}>
        {loadError !== null ? (
          <section className="empty-state">
            <h1>The Library could not load</h1>
            <p>{loadError}</p>
          </section>
        ) : cards === null ? (
          loading
        ) : cards.length === 0 ? (
          <section className="empty-state">
            <h1>No charts yet</h1>
            <p>
              Paste a frame, bind it, draw it — saved charts appear here as
              live cards, each rendered from its cached bind.
            </p>
            <p className="empty-state-cta">
              <Link to="/charts/new" className="ghost-button">
                New chart
              </Link>
            </p>
          </section>
        ) : flint === null ? (
          loading
        ) : (
          <div className="library-grid">
            {cards.map((card) => (
              <LibraryCard
                key={card.id}
                card={card}
                backend={backend}
                flint={flint}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
