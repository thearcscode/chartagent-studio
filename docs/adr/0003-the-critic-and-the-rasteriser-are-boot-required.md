# 3. The critic and the rasteriser are boot-required

- **Status:** Accepted
- **Date:** 2026-10-07
- **Settled on:** parent spec [#53](https://github.com/thearcscode/chartagent-studio/issues/53); tickets [#54](https://github.com/thearcscode/chartagent-studio/issues/54), [#55](https://github.com/thearcscode/chartagent-studio/issues/55), [#56](https://github.com/thearcscode/chartagent-studio/issues/56)
- **Builds on:** Studio ADR-0002 (the agent is built at boot; the key variable is derived from the model's provider prefix), ADR-0003 (the reference rasteriser renders in a browser), ADR-0026 (Tier 2 and the critique leaf call)

## Context

`create_chart_agent` reviews a plan's chart in two tiers. Tier 2 needs pixels (a
`Rasteriser`) and an independent model that looks at them (the critic). Both are
configuration the operator owns, and both can be absent in a way that would only show up
on the first plan.

## Decision

### 1. Both are boot-required

A container that cannot critique or rasterise does not start. `CRITIQUE_MODEL` is checked
for its provider key, and `RENDERER_VENDOR_DIR` is loaded through the library's
`load_vendored_renderers` (a missing directory or sha mismatch is a
`StudioConfigurationError` naming the setting), both before the agent is built. This is
the same discipline as ADR-0002 D3: fail loudly at boot rather than 500 on a user's first
plan, or worse, silently ship charts nobody reviewed.

### 2. The critic never falls back to the planner

`CRITIQUE_MODEL` has its own default (`anthropic:claude-sonnet-5`) and its own key
derivation (`<PROVIDER>_API_KEY` from its prefix). When it is unset it is **not**
`PLANNER_MODEL`. A critic that is the planner is not independent: it shares the planner's
blind spots, and changing `PLANNER_MODEL` would silently change the reviewer. Compose and
`Settings` carry the same default so the two cannot drift.

### 3. The rasteriser is the library's reference implementation

Studio runs `chartagent.rasterise.BrowserRasteriser` rather than its own renderer. The
review is only meaningful if the pixels match what the library's checks were validated
against (ADR-0003), and the renderer runtimes are pinned by sha in the library's
`vendor.json`. A Studio-owned rasteriser would be a second thing to keep in step with
those pins for no product gain.

### 4. The image carries what boot needs, installed at build time

- The `review` extra is installed (`chartagent[anthropic,review]`), which brings Playwright.
- Chromium is installed with `playwright install --with-deps chromium` during the image
  build, into a pinned `PLAYWRIGHT_BROWSERS_PATH`. Installing on first request would
  download hundreds of megabytes inside a running container (the same reason DuckDB's
  `httpfs` is installed at build).
- `RENDERER_VENDOR_DIR` is set to `/srv/chartagent/tools/paint/vendor` in the image, as
  `WEB_DIST_DIR` is. The app is installed `--no-editable`, so the installed package
  ships none of the vendored bytes and the path cannot be derived from it.

## Consequences

- The runtime image is larger (Chromium and its system libraries). It is still
  `python:3.12-slim` with no Node.
- Every deployment needs a key for the critic's provider as well as the planner's.
- Bumping `LIBRARY_GIT_SHA` moves the vendored renderers; a mismatch fails boot, not a
  request.

## Related

- Studio ADR-0002 — boot-time agent construction and key derivation.
