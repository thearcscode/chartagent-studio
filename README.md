# Chartagent Studio

The hosted product built on the [`chartagent`](https://github.com/thearcscode/chartagent)
library. The server binds; the browser compiles. No planner, no LLM in this
phase — a saved chart is a document, and re-rendering it against fresh data is
a `$0.00` replay of the stored transform.

## Layout

One repo, two languages:

- `app/` — FastAPI, one uvicorn process, Python 3.12. Sync `def` for anything
  that will call `bind`; `async def` for pure I/O.
- `web/` — Vite + React + TypeScript SPA, styled with plain CSS custom
  properties. No UI kit, no Tailwind, no CSS-in-JS.

Node is a build-time tool only; the runtime image is `python:3.12-slim` plus
built static assets.

## The library dependency

`app/pyproject.toml` declares `dependencies = ["chartagent>=0.1"]` and never
changes it. The source is supplied separately:

- **dev**: `[tool.uv.sources]` points at a local editable checkout
  (`../../chartagent`).
- **CI**: the library is checked out at the pinned `LIBRARY_GIT_SHA` as a
  sibling directory, so the same path source resolves to the pin and never to
  a contributor's working tree. While the library repo is private this needs a
  `CHARTAGENT_REPO_TOKEN` secret (a fine-grained PAT with read access); once
  the library is public the token lines can be deleted.
- **deploy**: the `Dockerfile` copies the pinned sibling checkout into the
  image and installs it non-editable. The build context is the parent
  directory of both checkouts:
  `docker build -f chartagent-studio/Dockerfile .`
- **after the PyPI release**: the sources block is deleted.

There is no `sys.path` route past the public API; a test asserts the import
resolves outside this repo.

## Auth

Clerk from day one. The SPA uses Clerk's prebuilt components restyled through
the appearance API against the vendored tokens; the server verifies the
session JWT locally against cached JWKS — no Clerk API call per request.
`owner_id` is the Clerk user id.

Environment:

| Variable | Where | What |
| --- | --- | --- |
| `VITE_CLERK_PUBLISHABLE_KEY` | web build | Clerk publishable key, inlined by Vite |
| `CLERK_JWKS_URL` | app | `https://<your-clerk-host>/.well-known/jwks.json` |
| `CLERK_ISSUER` | app | optional; the instance's Frontend API domain, verified as `iss` when set |
| `CLERK_AUTHORIZED_PARTIES` | app | optional JSON list of allowed `azp` origins |
| `WEB_DIST_DIR` | app | defaults to `web/dist` beside `app/` |
| `DATABASE_URL` | app + alembic | defaults to the compose db, `postgresql+psycopg://studio:studio@localhost:5432/studio` |
| `OBJECT_STORE_DIR` | app | dev object store root; defaults to `./.objects` |
| `UPLOAD_MAX_BYTES` | app | upload cap, default 50 MiB — configuration, never a literal |
| `BIND_ROW_CAP` | app | bind row cap, default 100000 — raises rather than truncates |
| `BIND_TIMEOUT_SECONDS` | app | DuckDB statement timeout passed to `bind`, default 30 |
| `REQUEST_TIMEOUT_SECONDS` | app | whole-request backstop, default 120 |
| `STUDIO_TEST_DATABASE_URL` | tests | a disposable database the test session creates, migrates and truncates |

## Local services

`compose.yaml` declares the two-service shape — the web container beside
Postgres (managed in deploys; the host vendor is unchosen). The web container
migrates at boot (`alembic upgrade head`) before serving.

## Design tokens

`web/src/tokens.css` is vendored **byte-identically** from the library repo's
`design/tokens.css`; `web/src/tokens.source-sha` records the SHA it was taken
from. CI diffs the copy against the canonical file at the pinned library SHA.
Change values upstream, never here. Dark is the default theme; the toggle
persists in `localStorage`.

Fonts (Instrument Serif, IBM Plex Sans, IBM Plex Mono — all SIL OFL 1.1) are
self-hosted woff2 under `web/public/fonts/`. Nothing is fetched from a CDN at
runtime.

## Develop

One-time setup:

```bash
cd app && uv sync                 # resolves chartagent from ../../chartagent
cd web && npm ci
cp app/.env.example app/.env      # fill in CLERK_JWKS_URL
cp web/.env.example web/.env      # fill in VITE_CLERK_PUBLISHABLE_KEY
```

Every session — database, then the two dev servers:

```bash
docker compose up -d db                       # Postgres on :5432
cd app && uv run alembic upgrade head         # create/migrate the five tables

# terminal 1 — API on :8000 (reads app/.env)
cd app && uv run uvicorn studio.main:create_app --factory --reload

# terminal 2 — SPA on :5173, proxying /api to :8000
cd web && npm run dev
```

Or run the whole thing in containers instead — the image migrates the
database at boot, so this is the full stack in one command (the Clerk
variables must be in the shell environment or a `.env` beside
`compose.yaml`):

```bash
docker compose up --build         # db + the built app on :8000
```

## Checks

```bash
cd app && uv run ruff check src tests && uv run mypy --strict src tests && uv run pytest
cd web && npm run typecheck && npm run lint && npm test && npm run build
```

The Playwright smoke (`cd web && npm run test:e2e`) is CI-only: it needs a built SPA, the API, Postgres, and Clerk testing credentials (`CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `CLERK_JWKS_URL`, `E2E_CLERK_USER_EMAIL`). It is not part of the local default checks.

`pytest` needs a Postgres it may create and truncate a disposable database
on; point `STUDIO_TEST_DATABASE_URL` at one (the default assumes the compose
db and uses `studio_test`).
