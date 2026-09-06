# 2. The planner extra is Studio's to ask for, and the agent is built at boot

- **Status:** Accepted
- **Date:** 2026-09-06
- **Settled on:** the grilling session of 2026-09-06; spec [#17](https://github.com/thearcscode/chartagent-studio/issues/17)
- **Builds on:** ADR-0006 (Studio is a plain public-API consumer with no exception),
  ADR-0020 (`create_chart_agent(model=...)`; the model client rides in a per-vendor
  extra)
- **Amends:** `AGENTS.md`'s hard rule *"`dependencies = ["chartagent>=0.1"]` in
  `app/pyproject.toml` **never changes**"* — see Decision 1.

## Context

`README.md` and `AGENTS.md` both carry a rule that has held since #20: the library
dependency line never changes, because the *source* is supplied separately (an editable
path in dev, a pinned SHA in CI and deploy) and there must be no second place where
Studio re-pins or side-loads the library.

The planner needs `pydantic-ai`, which the library ships as an optional extra —
`chartagent[anthropic]` — and which `ModelClient._extra_to_install()` names in the very
error it raises when the extra is missing. So the ticket runs straight into the rule, and
the rule has to be read rather than obeyed literally.

## Decision

### 1. `chartagent[anthropic]>=0.1` — the rule governs the pin, not the extras set

The line becomes `chartagent[anthropic]>=0.1` and `AGENTS.md` is amended **in the same
change**, so the rule and the code never disagree.

The rule exists so that Studio never re-pins the library and never reaches past its
public API. Adding an extra does neither: the version constraint is unchanged, the
source blocks are unchanged, and asking the library for a capability the library itself
declares and documents is the opposite of reaching around it.

**Rejected: `pydantic-ai-slim[anthropic]` as a direct Studio dependency.** It leaves the
sacred line untouched and is worse — Studio would hard-code the library's private
transport choice, and the day chartagent swaps model clients or renames its extra,
Studio installs cleanly and fails at runtime. A documentation problem traded for a
silent-drift problem.

### 2. `PLANNER_MODEL`, and one `ChartAgent` on `app.state`

`PLANNER_MODEL` is a `Settings` field — bare, matching `bind_row_cap` and
`request_timeout_seconds`, not `STUDIO_`-prefixed — holding a pydantic-ai model string,
defaulting to `anthropic:claude-sonnet-4-6`. That is the string the library's PRD and
`create_chart_agent` tests use. A newer Anthropic alias is not a drop-in: Studio does
not pick models, it consumes the planner, so the default is the one the planner was
written against.

One `ChartAgent` is constructed in `create_app` and held on `app.state`. `ChartAgent`
documents that it holds the model string and one client with **no per-request mutable
state**, so per-request construction would buy nothing and pay provider setup on every
plan.

**No UI model picker and no per-user keys.** Studio is a demonstrator with one operator;
a picker is a product surface nobody asked for and per-user keys are a credential store
ADR-0006 D10 spent real effort avoiding.

### 3. The boot check replaces a leaked `UserError`; it does not catch an escape

At pydantic-ai 2.40.0, `Agent.__init__` resolves the model eagerly via
`models.infer_model(model)`, and the provider raises on a **missing API key at
construction** — as `pydantic_ai.exceptions.UserError`, which `ModelClient.__init__`
does not catch (it catches `ModuleNotFoundError` and `ImportError`, and maps only those
to `ModelClientUnavailableError`).

So boot already fails on a missing key. The check's job is **the message, not the
failure**: `create_app` verifies the provider's environment variable before constructing
the agent and raises a Studio configuration error, so a misconfigured deployment reports
its own fault instead of leaking a third-party error that names a library the operator
never installed directly.

The variable name is **derived from `PLANNER_MODEL`'s provider prefix** —
`model.split(":", 1)[0]`, the same split `_extra_to_install` uses — never hard-coded to
`ANTHROPIC_API_KEY`. Changing `PLANNER_MODEL` to an OpenAI string must not leave the
check silently validating the wrong variable.

Both failures stay **loud and at boot**, consistent with the flint-pin-mismatch
discipline: a mismatched pin fails at load rather than compiling against the wrong
vocabulary, and a missing key fails at boot rather than 500-ing on the first plan.

## Consequences

- **Every deployment needs a provider key to serve any route**, including the ones that
  never plan, because the agent is built at boot. That is the price of failing loudly,
  and it is deliberate.
- **The existing test factory must supply a dummy key** before `create_app`, or all
  twelve `make_app` call sites and the `app` fixture die at boot. A dummy string is
  enough: the provider raises on the variable's absence, not on its validity. Tests that
  exercise the plan route replace the agent on `app.state` with a stub and make no real
  model call.
- **`AGENTS.md`'s "Where things live" table is retargeted in the same change**: Studio
  ADRs and tickets live in this repo, `CONTEXT.md` stays in the library repo, and the
  *"No planner, no LLM"* framing goes.
- **The extras set is now a thing Studio can drift on.** Switching `PLANNER_MODEL` to an
  OpenAI model requires `chartagent[openai]` too; the boot check catches the missing key
  but the missing extra surfaces as `ModelClientUnavailableError` at construction, which
  is also boot. Both are loud; neither is automatic.

## Evidence

- `../chartagent/src/chartagent/plan/client.py` — `_extra_to_install()` returns
  `chartagent[anthropic]` for shipped extras; `ModelClient.__init__` catches only
  `ModuleNotFoundError` and `ImportError`.
- `../chartagent/pyproject.toml` — `[project.optional-dependencies]` declares
  `anthropic` and `openai`.
- Measured 2026-09-06 against pydantic-ai 2.40.0 with `ANTHROPIC_API_KEY` unset:
  `Agent('anthropic:claude-sonnet-4-5', retries=0)` raises `UserError` at construction
  ("Set the `ANTHROPIC_API_KEY` environment variable…"), confirming eager resolution.
- `app/src/studio/config.py` — `Settings` field names are bare, no `STUDIO_` prefix.
- `app/tests/conftest.py:121` — `make_app` calls `create_app(settings)`; twelve call
  sites plus the `app` fixture.

## Related

- Studio ADR-0001 — what the agent is called for and what a plan produces.
- ADR-0020 — `create_chart_agent`'s surface and the per-vendor extra.
