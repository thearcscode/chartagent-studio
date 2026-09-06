# 1. The instruction box plans a draft, and the browser compiles it

- **Status:** Accepted
- **Date:** 2026-09-06
- **Settled on:** the grilling session of 2026-09-06; spec [#17](https://github.com/thearcscode/chartagent-studio/issues/17)
- **Builds on:** ADR-0005 (`bind` is the public seam), ADR-0006 (the server binds and
  the browser compiles — D1's request flow, D3's threadpool, D9's four caps, D13's one
  error table), ADR-0007 (the five tables; D4 save is an explicit user action; D6 the
  bind cache and the runs row), ADR-0020 (the planner's public surface — `create_chart`
  has no `backend=`, and `bind`'s errors surface un-wrapped through it), ADR-0021
  (two-tier backend selection — **Studio passes nothing**)
- **Decides nothing about:** the custom rail, `history=`, `quality=`, the sandbox, a
  per-user model choice, or a create-time backend picker (ADR-0021 D1 leaves that one
  fog, and this ADR does not clear it).
- **Amends:** `AGENTS.md`'s *"No planner, no LLM, no generated code in this phase (P0)"*
  — true of P0 and false from this ticket on.

## Context

The library shipped `create_chart_agent` / `create_chart` (chartagent#116). Studio has
had a frame editor since #74: paste a frame, bind it, draw it, save it. The instruction
box is the phase change — Studio's first model call — and the question this ADR answers
is not *how* to call the planner (one call, documented) but **what a plan is in Studio's
own model**: an operation on a chart, or a way to fill the editor.

Two findings decided most of it.

**The library's result is already the shape Studio's client eats.** `Envelope.input` is
`frame.model_dump(mode="json", by_alias=True, exclude_none=True)` with nulls omitted,
plus the bound rows attached at `data` — so the frame is recoverable by removing one
key, which is precisely what `ChartResult.refresh` does before re-binding. And the SPA
already has exactly one client path every bind shares — `drawEnvelope(envelope,
backend, boundContent)` — which compiles, runs the row-count honesty guard, and either
draws or refuses. A plan therefore needs **no new compile path, no new renderer path,
and no second bind**. It needs a frame, and the frame is `envelope.input` minus `data`.

**`runs.chart_id` is `NOT NULL`.** Whether a plan is audited in the `runs` table is
therefore not a preference to be weighed — it follows mechanically from whether a plan
has a chart, which is Decision 1. This is the clearest case in the design of a schema
fact settling a product question.

## Decision

**A plan produces a draft: an unsaved frame in the editor, drawn from a real bind, that
the existing Save turns into an ordinary revision.**

### 1. A plan produces a draft, not a revision

`POST /api/specs/plan {instruction, source_id}` writes **nothing** to the database. It
returns the frame and the envelope; the SPA puts the frame in the editor and draws the
picture. Saving stays what ADR-0007 D4 made it: one explicit user action, numbered
immutable revisions, a no-op on byte-identical content.

The rejected alternative — the route creates the chart, revision 1 and the cache and
returns a `SpecOut` — costs fewer clicks and buys a second write path into
`spec_revisions`, plus a permanent revision for every abandoned attempt. Planning is a
*source of frame text*, not a second way to author history.

A consequence worth naming plainly: **a plan on an already-saved chart is just a draft
too.** Re-planning a saved chart and saving it is revision N+1 through the existing edit
path, with no special case anywhere.

### 2. `PlanOut` is `BindOut` plus one field, and `BindOut` does not change

```
PlanOut = BindOut's keys + plan_elapsed_ms
```

The plan route's response carries every key `POST /api/specs/bind` already returns —
`flint_version`, `backend`, `input`, `row_count`, `elapsed`, `warnings`,
`source_schema` — so the client's existing compile path takes it unmodified. The one
addition is `plan_elapsed_ms` (Decision 7). **`BindOut` itself is untouched**: the bind
routes gain no field they have no value for, and a test asserts `BindOut` has no
`plan_elapsed_ms` so the two cannot quietly converge.

### 3. The client strips `data`, not the server

One helper in the SPA — `frameFromEnvelope()` — removes `data` from `envelope.input`,
and its result feeds **both** the editor textarea and `lastBind.content`.

Server-side stripping was rejected for a blunt reason: it would ship the rows twice in
one response, up to `BIND_ROW_CAP` of them. The client needs the stripped frame for
display regardless — a textarea holding 100,000 rows is not an editor — so the function
has to exist client-side whatever the server does.

### 4. Save writes the cache off the plan's own bind; nothing binds twice

The plan result goes through `drawEnvelope`, which sets `lastBind`, which the existing
Save turns into the posted `bind` block — backend, content, rows, `elapsed_ms`,
`source_schema`. The server re-checks cache honesty against the posted frame exactly as
it does today (ADR-0007 D8 erratum). **A plan followed by a save is one bind, not two.**

### 5. No `runs` row, and the instruction is not persisted

A draft has no chart, and `runs.chart_id` is `NOT NULL`, so a plan writes no run. It is
recorded in the structured stdout log as a plan event instead, beside the existing
`log_bind`.

The instruction itself is **not stored at P1**. Nothing reads it: there is no
`history=`, no re-plan-from-stored-instruction, and the Library card renders from the
bind cache. Storing it per revision would be actively wrong against
`UNIQUE (chart_id, content_hash)` — two instructions converging on the same frame are
already one revision, so the column would keep the first instruction and drop the
second, i.e. be wrong exactly when it is most interesting. If the ask ever needs
rendering, `charts.created_from_instruction` is an additive migration to be made **by
the ticket that first renders it**, not speculatively now; it goes stale on a re-plan
and save, and a column that lies is worse than a column that is absent.

### 6. Studio passes no backend, and the picker snaps to what the ranking chose

ADR-0021 D1 is adopted without qualification: Studio is a plain caller, sends no
`default_backend`, and does not feed `requested_backend`. A user who wants ECharts says
so in the instruction and step 1 extracts it.

**The picker snaps to `envelope.backend` when a plan returns, and this is load-bearing,
not cosmetic.** The picker's initial state is `echarts`; the ranking's first survivor is
`vegalite`. Without the snap the control would name a backend that did not draw the
chart. One line of UI text says the planner chose it — with no `requested_backend` most
instructions land on Vega-Lite, and a user who assumed the picker was consulted needs to
know it was not. A later pick is the existing preview bind of the frame now in the
editor: no re-plan, no model call.

### 7. The cost line names the plan, and drops it on the next bind

The line reads `{rows} rows · {n} ms bind · {n} s plan · {backend}` after a plan, and
loses the plan term on every subsequent bind or refresh of that chart. That contrast —
seconds and money once, milliseconds and `$0.00` forever after — is the product's
central argument, and it was invisible in a line that only ever showed
`envelope.elapsed`.

`plan_elapsed_ms` is Studio wall time around `create_chart` minus `round(elapsed * 1000)`,
clamped at 0: `envelope.elapsed` covers only the internal bind, and the clamp keeps a
timing race from printing a negative. **No token counts and no dollar figures** —
`ChartResult` carries no usage data, so any such number would be invented.

### 8. Concurrent plans are capped by a semaphore; the overflow is 503

A `threading.Semaphore` with a configured cap, acquired non-blocking, released in
`finally`; a refused acquire is **503**. A plan is 2–5 model calls and seconds long, so
it is a qualitatively different tenant of Starlette's threadpool than a millisecond
`bind` — enough concurrent plans and the pure-I/O routes starve behind them. This is ten
lines that keep the sub-millisecond routes the architecture exists to demonstrate.

Not a queue and not a worker: those are P2 shapes. And note what the cap does **not**
do — a request that dies on `REQUEST_TIMEOUT_SECONDS` does not free the slot, because
that backstop does not cancel the thread (Consequences).

### 9. The row cap is enforced post-hoc; the statement timeout cannot be

`create_chart` takes no `timeout=`, so `BIND_TIMEOUT_SECONDS` **cannot reach the bind
the planner runs internally**. Of ADR-0006 D9's four caps, three still hold on this path
— the upload cap at registration, the request backstop, and the row cap, which is
checked on `envelope.row_count` after the call and raises the same
`RowCapExceededError` `_do_bind` raises, with the same wire shape. The statement timeout
is a recorded gap (Consequences), not a silent one.

### 10. Four new rows in the one error table, and vendor errors are wrapped

ADR-0006 D13's table gains the planner's four `ChartAgentError` subclasses:

| Error | Status | `error` code | Carried fields |
| --- | --- | --- | --- |
| `InexpressibleRequestError` | 422 | `inexpressible_request` | `bucket` |
| `UnanswerableInstructionError` | 422 | `unanswerable_instruction` | `kind`, `keys` |
| `PlannerFailureError` | 502 | `planner_failure` | `reason` |
| `ModelClientUnavailableError` | 500 | `model_client_unavailable` | `extra` |

`UnanswerableInstructionError` is the one the UI can act on — it names the columns or
source buckets the instruction assumed and the source does not have.
`BackendCapabilityError` needs no new row: ADR-0021 D3 gave it a second raise site, not
a second type, and it is already mapped.

`ModelClient` documents that transport, auth and model-string errors **propagate
un-wrapped** and are not `ChartAgentError` subclasses, so `except ChartAgentError`
misses them. The plan route catches them and re-raises a Studio type mapped to **502**
with a request id and no vendor detail — a rate limit or a vendor outage is the most
likely production failure of this route and must not read as a Studio bug. **The global
unmapped-exception 500 is unchanged**; the wrapping is local to the plan route.

### 11. The disclosure is persistent; consent is deferred and named

The data profile carries ten sample rows, per-column top values, and string `min`/`max`
— real customer cell values — and the instruction goes with them. A persistent one-line
disclosure sits at the instruction box naming what leaves (a profile of this source,
including sample values, plus your instruction) and where it goes (the configured model
vendor).

**No consent gate at P1**, deliberately: a gate implies a stored consent record, which
is a schema change and a P2-shaped decision, and Studio is a demonstrator with one
operator. Recorded here so the deferral is a decision rather than an oversight.

**Studio never profiles.** `create_chart` does it internally; a Studio-side profile is
already on `CONTEXT.md`'s *Avoid* list for **Data profile**, and this is the ticket that
could most plausibly have violated it.

## Consequences

- **`BIND_TIMEOUT_SECONDS` does not reach the planner's bind.** `create_chart` accepts
  no `timeout=`, so DuckDB runs unbounded inside it and `REQUEST_TIMEOUT_SECONDS` is the
  only backstop. That backstop **does not cancel the thread**: a timed-out plan returns
  a response to the client while the thread keeps running and keeps holding its
  semaphore slot until the model calls and the bind actually finish. This implies a
  library ticket (a `timeout=` passthrough on `create_chart`); it is not filed by this
  ADR and the library is not patched here.
- **A URL source is read twice per plan** — once by `profile_source`, once by the
  internal `bind`. An upload is materialised once to a temp file and read twice from
  disk. For a large remote Parquet this doubles the fetch, and Studio cannot avoid it:
  `create_chart` takes one `DataSource`.
- **Every deployment and every test now needs a provider key at boot**, because the
  agent is constructed in `create_app` (Studio ADR-0002). The existing test factory must
  supply a dummy value or the whole suite dies at boot — the provider raises on the
  variable's *absence*, not on its validity.
- **A plan is the only action in Studio that destroys editor content irrecoverably.**
  Revisions are saved; the textarea is not, and React state has no undo. Hence the
  confirm before the POST when the editor is non-empty and differs from the last saved
  revision.
- **The four rejection paths are now user-visible product surface.** Inexpressible,
  unanswerable, planner failure and vendor outage each get a distinct message. Before
  this ticket Studio had no failure that was the *model's* rather than the data's.

## Alternatives rejected

- **A plan creates the chart, revision 1 and the cache in one shot.** Fewer clicks; a
  second write path into `spec_revisions`, a permanent revision per abandoned attempt,
  and a forked save path. See Decision 1.
- **The server returns the stripped frame as an extra field.** Would ship the rows twice
  and would not spare the client the helper it needs for display anyway. See Decision 3.
- **An instruction column on `spec_revisions`.** Broken against
  `UNIQUE (chart_id, content_hash)`. See Decision 5.
- **`charts.created_from_instruction` now.** Goes stale on a re-plan and save, and
  nothing reads it yet. Deferred to the ticket that renders the ask.
- **429 for the concurrency overflow.** 503 is the honest code: the server is
  temporarily out of a resource, not the client over a quota.
- **Letting vendor errors fall through to the global 500.** Makes a vendor outage
  indistinguishable from a Studio bug in the one place they are most likely to be
  confused.

## Evidence

- `../chartagent/src/chartagent/bind.py:116` — `envelope.input` is the normalised frame
  dump plus attached `data`, confirming the frame is recoverable by removing one key.
- `../chartagent/src/chartagent/result.py` — `ChartResult.refresh` strips `data` before
  re-binding; the same rule, stated by the library.
- `../chartagent/src/chartagent/plan/agent.py:87` — `bind(frame, data, backend=backend)`
  with no `timeout=`, against `app/src/studio/routes/charts.py:475` which passes
  `timeout=settings.bind_timeout_seconds`.
- `app/src/studio/models.py:178` — `runs.chart_id` is `NOT NULL`.
- `app/src/studio/models.py:98` — `UNIQUE (chart_id, content_hash)` on `spec_revisions`.
- `web/src/pages/ChartPage.tsx:220` — `drawEnvelope(envelope, backend, boundContent)`,
  the one client path; `:146` — the picker's `useState<Backend>("echarts")`, against
  `BACKEND_RANKING`'s first survivor `vegalite`.
- `web/src/pages/ChartPage.tsx:551` — Save builds its `bind` block from `lastBind`,
  including `rows: lastBind.envelope.input.data.values`.
- `../chartagent/src/chartagent/profile/models.py` — `SAMPLE_ROWS = 10`, `TopValue`, and
  `StringStats.min`/`.max`, all classified `UNTRUSTED` because they are copied data.

## Related

- Studio ADR-0002 — the extra, `PLANNER_MODEL`, and the agent built at boot.
- ADR-0020, ADR-0021 — the planner's public surface and why Studio passes no backend.
- ADR-0007 — the five tables; D4 and D6 are what Decision 1 declines to touch.
