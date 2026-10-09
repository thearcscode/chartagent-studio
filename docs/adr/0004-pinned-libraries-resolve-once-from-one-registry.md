# 4. Pinned libraries resolve once, from one registry

- **Status:** Accepted
- **Date:** 2026-10-09
- **Settled on:** parent spec [#62](https://github.com/thearcscode/chartagent-studio/issues/62); tickets [#63](https://github.com/thearcscode/chartagent-studio/issues/63), [#64](https://github.com/thearcscode/chartagent-studio/issues/64), [#65](https://github.com/thearcscode/chartagent-studio/issues/65), [#66](https://github.com/thearcscode/chartagent-studio/issues/66), [#67](https://github.com/thearcscode/chartagent-studio/issues/67)
- **Builds on:** library ADR-0017 (Decisions 10-12: pins, the single registry, a free URL refused), library ADR-0030 (Decisions 6-8: the resolver returns bytes off the result; resolution failure ends the call), Studio ADR-0002 (boot-time agent construction), library ADR-0007 (the bind cache)

## Context

A custom-rail chart may pin a third-party library (ECharts, Plotly). Until #62 Studio
refused every such recipe at save, open, paint and refresh. The library already supplies
`LibraryPin`, `build_shell` (which verifies pins against supplied bytes) and the agent's
private library resolver; Studio had to supply the resolution, the byte store and the
hand-off to `build_shell`.

## Decision

### 1. One registry host: `https://registry.npmjs.org`

A pin is a package name and a version. Resolution contacts `https://registry.npmjs.org`
and no other host. (jsDelivr appears in library ADR-0017 only as a size measurement, not
as a source.) The set of code that can run in a user's browser is bounded by that one
registry.

### 2. A pin's bytes are the version's browser-entry file; the sha256 is that file's hash

The stored bytes are the single file the version's `package.json` names for a browser
global. The pin's sha256 is the hash of **that file**, not of the tarball. The tarball is
a transport detail; the file is what `build_shell` embeds, hashes into the CSP and
verifies, so it is what the pin must name.

### 3. Studio installs the resolver at boot

Studio sets `ChartAgent._library_resolver` once, when it builds the agent. Resolution
happens only when a pin is authored (the agent names a library), returns
`(sha256, bytes)`, and writes the bytes to the content-addressed blob store. Bytes never
ride `ChartResult`, `ChartDocument` or `ChartRecipe`. Paint and refresh read the blob
store by sha256 and pass the bytes to `build_shell`; render is offline and never calls
the resolver. With the resolver unset a plan cannot pin a library, so the agent writes
from scratch.

### 4. A free URL stays refused

A library source is `(name, version)` against the registry above, never a URL. Studio's
server is not a fetcher for arbitrary hosts (library ADR-0017 Decision 10).

### 5. The pinned-library refusal is retired

`PinnedLibrariesError`, `ensure_supported`, its error-table row and handler, and the
client's "unsupported" card for it are removed. Missing or corrupt stored bytes surface
as per-card `library_missing` / `library_corrupt` errors from `build_shell`, not as a
refusal of pinned recipes.

### 6. `theme_spec` stays stored and unapplied on the custom rail

`theme_spec` is stored with the recipe as before and is never validated or applied
(library ADR-0018 Decision 3). The channel's `theme` payload is Studio's current data
palette, exactly as for a from-scratch chart. A later release may apply it without
re-authoring anything.

## Consequences

- The first load of a pinned card is the expensive one (ECharts roughly 1 MB, Plotly
  4-5 MB); the in-process blob cache makes a multi-card Library page acceptable.
- A saved chart keeps painting if the registry changes or vanishes, because bytes are
  content-addressed and pinned by hash.
- Authoring needs egress to `registry.npmjs.org`; rendering does not.

## Related

- Studio ADR-0002 — boot-time agent construction.
- Studio ADR-0003 — boot-required collaborators.
