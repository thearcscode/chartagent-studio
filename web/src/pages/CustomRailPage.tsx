/** A private proving ground for the custom rail's parent side (#33): a
 * hand-written fixture document mounted in a sandboxed iframe, with the
 * paint signal shown plainly. Reachable by URL only — not in navigation.
 */

import { useAuth, UserButton } from "@clerk/react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { SandboxedPaint } from "../components/SandboxedPaint";
import { fetchFixture, type FixtureShell } from "../lib/fixtures-api";
import { dataPaletteTheme } from "../lib/palette";
import { CHART_STAGE } from "../lib/stage";
import { getStoredTheme, setTheme, type Theme } from "../theme";

const FIXTURE_NAMES = ["drawing", "throwing"] as const;

export function CustomRailPage() {
  const { fixture = FIXTURE_NAMES[0] } = useParams();
  const known = (FIXTURE_NAMES as readonly string[]).includes(fixture);
  return known ? <FixtureView name={fixture} /> : <NotFound />;
}

function NotFound() {
  return (
    <div className="app-shell">
      <p role="alert">Not found.</p>
      <Link to="/custom-rail">Back to the custom-rail page</Link>
    </div>
  );
}

function FixtureView({ name }: { name: string }) {
  const { getToken } = useAuth();
  const navigate = useNavigate();
  const [theme, setThemeState] = useState<Theme>(() => getStoredTheme(localStorage));
  // Results are tagged with the fixture they answer, so a switch reads as
  // loading without resetting state inside the effect.
  const [loaded, setLoaded] = useState<{
    name: string;
    shell?: FixtureShell;
    error?: string;
  } | null>(null);
  // The data palette is identical in both themes: the toggle asks for a
  // fresh paint through `repaintKey`, not by changing the theme object.
  const paletteTheme = useMemo(() => dataPaletteTheme(), []);
  const current = loaded?.name === name ? loaded : null;

  useEffect(() => {
    let cancelled = false;
    fetchFixture(getToken, name)
      .then((shell) => {
        if (!cancelled) setLoaded({ name, shell });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLoaded({ name, error: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [getToken, name]);

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
        {FIXTURE_NAMES.map((fixtureName) => (
          <button
            key={fixtureName}
            type="button"
            className="ghost-button"
            aria-pressed={name === fixtureName}
            onClick={() => navigate(`/custom-rail/${fixtureName}`)}
          >
            {fixtureName}
          </button>
        ))}
      </div>
      <section className="stage-pane">
        {current?.error !== undefined ? (
          <p className="paint-signal" role="alert" data-signal="failed">
            Did not load the fixture. {current.error}
          </p>
        ) : current?.shell === undefined ? (
          <p className="paint-signal" role="status" data-signal="drawing">
            Loading…
          </p>
        ) : (
          <SandboxedPaint
            key={name}
            shell={current.shell}
            rows={current.shell.rows}
            theme={paletteTheme}
            repaintKey={theme}
            size={CHART_STAGE}
          />
        )}
      </section>
    </div>
  );
}
