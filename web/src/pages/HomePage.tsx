import { useAuth, UserButton } from "@clerk/react";
import { useEffect, useState } from "react";

import { apiFetch } from "../api";
import { getStoredTheme, setTheme, type Theme } from "../theme";

export function HomePage() {
  const { getToken } = useAuth();
  const [ownerId, setOwnerId] = useState<string | null>(null);
  const [theme, setThemeState] = useState<Theme>(() =>
    getStoredTheme(localStorage),
  );

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/me", getToken)
      .then((response) =>
        response.ok ? response.json() : Promise.reject(new Error(String(response.status))),
      )
      .then((body: { owner_id: string }) => {
        if (!cancelled) {
          setOwnerId(body.owner_id);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setOwnerId(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  function toggleTheme() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next, localStorage, document.body);
    setThemeState(next);
  }

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
      <main className="app-main">
        <section className="empty-state">
          <h1>No charts yet</h1>
          <p>
            The Library arrives with the draw ticket. You are signed in
            {ownerId ? (
              <>
                {" "}
                as <code>{ownerId}</code>
              </>
            ) : (
              ""
            )}
            .
          </p>
        </section>
      </main>
    </div>
  );
}
