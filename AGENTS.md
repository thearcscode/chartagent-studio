# Chartagent Studio — agent guide

The hosted product built on the `chartagent` library. **The server binds; the
browser compiles.**

This repo is self-contained code but not self-contained context. The library's
design system, ADRs, and `CONTEXT.md` live in the sibling checkout. Read them
before implementing anything.

## Where things live

| What | Where |
| --- | --- |
| Tickets | GitHub issues on **this repo**. The instruction box shipped as #17 / #18–#20. **GitHub is the only tracker — Linear is not used for this project, even if a Linear integration is configured; do not spend a step authenticating it.** Fetch with `gh issue view <n>`. |
| Vocabulary | `CONTEXT.md` in the library repo — read it first. |
| Architecture decisions | `docs/adr/` in this repo for Studio (Studio ADR-0001, ADR-0002). Library ADRs stay in `../chartagent/docs/adr/`: ADR-0006 (stack, request flow, pinning, refusals), ADR-0007 (five tables, bind cache, runs), ADR-0005 (the library surface this app consumes), ADR-0020 (planner surface). |
| Design system | `design/tokens.css` in the library repo is **canonical**; `design/README.md` carries the reasoning (two colour systems, type scale, rail hues are load-bearing). |
| The library itself | Local checkout at `../chartagent` (sibling of this repo). |

## Hard rules (from the ADRs; violations fail review)

- The library dependency's *version constraint and source* never change
  (`chartagent[anthropic]>=0.1` in `app/pyproject.toml`). Dev uses the
  editable path source; CI/deploy resolve the pinned git SHA
  (`LIBRARY_GIT_SHA` in `.github/workflows/ci.yml`) via a sibling checkout.
  Asking the library for one of its own extras is not a change to the pin.
  No `sys.path` hacks, no vendored library copy.
- **No UI kit, no Tailwind, no CSS-in-JS.** Plain CSS custom properties only.
- `web/src/tokens.css` is vendored **byte-identically** from the library's
  `design/tokens.css`; the source SHA is recorded in `web/src/tokens.source-sha`
  and CI diffs the copy against the canonical file at the pinned SHA. Change
  values upstream, never here.
- **Nothing is fetched from a CDN at runtime** — not Flint, not fonts, not
  renderers. Fonts are self-hosted woff2 in `web/public/fonts/`.
- Routes are SPA-private behind a Clerk session. No API keys, no OpenAPI
  promise, no versioned public HTTP API. The server verifies session JWTs
  locally against cached JWKS; `owner_id` is the Clerk user id.
- Sync `def` for any route that calls `bind`; `async def` for pure I/O.
- Dark theme by default; the toggle persists in `localStorage` only.
- Node is a build-time tool. The runtime image is `python:3.12-slim` plus
  built static assets.

## Checks (must all pass)

```bash
cd app && uv run ruff check src tests && uv run mypy --strict src tests && uv run pytest
cd web && npm run typecheck && npm run lint && npm test && npm run build
```

## Develop

```bash
cd app && uv sync                 # chartagent resolves from ../chartagent
cd web && npm ci
# app/.env needs CLERK_JWKS_URL and ANTHROPIC_API_KEY; web/.env needs VITE_CLERK_PUBLISHABLE_KEY
# (see the .env.example files)
cd app && uv run uvicorn studio.main:create_app --factory --reload
cd web && npm run dev             # SPA on :5173, proxies /api to :8000
```

## Workflow

- Tickets are claimed, implemented, and reviewed per the library repo's
  `docs/agents/issue-tracker.md`. Branch per ticket. **PRs are stacked**:
  each ticket's branch merges into the previous ticket's branch while the
  stack is open (feat/18 ← feat/19 ← feat/20), so `origin/main` lags the
  real work. Branch off the tip of the stack, not `main` — check
  `gh pr list --state all` and the branch tips first.
- Test seams are defined by the instruction-box spec (#17, "Testing decisions"): the
  HTTP API through the framework's test client, the chart agent on app
  state, one Playwright smoke test, component tests for client-side logic,
  the tokens diff. Do not re-test library behaviour — test that Studio
  carries what the library returns.

## Environment notes (learned the hard way)

- **`gh` needs network access.** The sandboxed shell blocks the GitHub API
  by default (`Post "https://api.github.com/graphql": Forbidden`); re-run
  the command with full network permission.
- **Use `uv run --no-sync` for pytest/ruff/mypy.** The sandbox cannot
  rewrite `app/.venv`, so plain `uv run` fails mid-sync ("Operation not
  permitted") and can churn `app/uv.lock` with unrelated metadata from the
  local library checkout. The venv is already installed; `--no-sync` runs
  straight through. Revert any `uv.lock` noise before committing.
- **App tests need Postgres on localhost:5432** (or
  `STUDIO_TEST_DATABASE_URL`). A local server provides it; Docker is not
  available in this environment.
- **Vitest has no `globals` or setup file.** Testing Library's auto-cleanup
  does not run — a test file with more than one `render()` needs an
  explicit `afterEach(cleanup)` or later tests match earlier renders'
  elements.
