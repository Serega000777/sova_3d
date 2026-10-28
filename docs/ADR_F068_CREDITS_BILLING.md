# ADR: F-068 AI Credits / Billing — Engineering Plumbing

**Status:** Accepted for shadow pricing; enforcement and real-money billing remain gated
**Scope:** Engineering architecture plus the versioned `2026-10-29.v1` action catalogue.
Subscription prices, included monthly credits, currencies and payment processors are handled in
the next separately verified block; this ADR does not authorize a real debit or charge.

## 0. Implemented checkpoint — 29.10.2026

- All 36 production job types have one positive, versioned credit quote in
  `app.services.pricing`; a test requires exact set equality with the registered runner handlers,
  so adding an unpriced production job fails CI.
- Authenticated `GET /api/v1/pricing` and `POST /api/v1/pricing/quote` expose the same canonical
  catalogue to web/mobile/desktop clients. Unknown actions and invalid quantities fail closed.
- Successful non-provider-metered jobs snapshot `pricing=2026-10-29.v1` and
  `quoted_credits` in the append-only ledger. `credits_delta` remains zero: the quote is visible,
  but no balance is silently reduced.
- The relative ladder is explicit: deterministic previews/metadata cost least, exact geometry is
  mid-tier, and vision/generative/reconstruction work costs most. These are product-credit quotes,
  not claims about a provider invoice or a fixed RUB/USD exchange rate.
- Production payment, top-up, refunds, subscription grants and enforcement remain disabled until
  their separately versioned commercial rules and provider are shipped.

## 1. Context

F-068 ("AI credits") is flagged MVP, not V2/V3. An audit characterized the codebase as having
"zero billing/credit infrastructure." That is half true. Reading the actual code:

**What already exists (built for a different purpose, but directly reusable):**

- `usage_ledger` (`services/api/app/models/usage.py`, migration `0004_usage_ledger.py`) is an
  **append-only** table (enforced by a DB trigger, per its docstring) with `workspace_id`,
  `job_id`, `ai_request_id`, `kind` (`ai_tokens | gpu_seconds | cpu_seconds | storage_bytes |
  credits`), `quantity`, `cost_usd`, and a **signed** `credits_delta` — "consumption is
  negative, top-ups/refunds positive" per its own comment. This is already the right shape
  for requirement 1 (ledger, not a mutable counter).
- `services/usage.py` is the single sanctioned write path (`record()`) and already computes a
  **derived balance** — `workspace_totals()` sums `credits_delta` on the fly
  (`credits_balance`). There is no separate mutable balance column anywhere. Good: this is
  exactly the auditable pattern requirement 1 asks for; it just needs more writers.
- Enforcement exists, but only for one path: the AI chat/command planner.
  `app/jobs/ai_command.py` rejects a plan whose cost exceeds `ai_budget_usd_per_job`;
  `app/services/ai_commands.py::enforce_budget` (T-047) refuses new AI work once a
  workspace's trailing-month `cost_usd` sum reaches `Workspace.ai_monthly_budget_usd` (or the
  global `Settings.ai_workspace_monthly_budget_usd` default). This is a **spend ceiling in
  USD**, not a prepaid credit balance — nothing ever posts a positive `credits_delta`, so
  "credits" today is a debit-only shadow of `cost_usd`.
- Metering actually fires in exactly **two** of ~30 registered job handlers:
  `ai_command` (via `ai_commands.record_usage`) and `diagnose_print_photo`
  (`app/jobs/diagnose_print.py`), both LLM/vision calls with a provider-reported token cost.
  Every other handler — `generate_mesh` (Shap-E text-to-mesh), `reconstruct_scan`,
  `analyze_print`/`optimize_print`/`slice_preview` (slicing), `export_job`, `edit_facade`,
  `auto_furnish`, `site_plan`, `house_box`/`house_walls`, `thumbnail`, etc. — runs for free
  today, with no ledger row at all, despite real CPU/GPU cost (Shap-E alone runs up to the
  full sandbox budget, ~15–30 min per shape per its own docstring).
- `Job` (`app/models/execution.py`) already has `idempotency_key` (unique per workspace),
  `attempts`/`max_attempts` (retries up to 3), and a strict status machine
  (`JobStatus`/`ACTIVE_JOB_STATUSES`/`TERMINAL_JOB_STATUSES`). A job can be attempted more
  than once under the same `job.id` — any metering keyed to job execution must dedupe on
  `job.id`, not on "handler ran," or a retried job double-charges.
- There is **no admin-configurable pricing surface anywhere in the app.** Every cost-like
  value (`ai_budget_usd_per_job`, `ai_workspace_monthly_budget_usd`) is a `pydantic` field on
  `Settings` (`app/config.py`) — an env var, changeable only by redeploy. There is no
  DB-backed config/feature-flag table precedent in `app/models/*` to build on; this would be
  new.
- There is **no platform-admin role.** `WorkspaceRole` (`owner|admin|editor|viewer`) is
  workspace-scoped — its "admin" is a workspace admin, not a platform operator. Any admin
  pricing UI needs a new authorization concept that doesn't exist yet.
- F-004 Marketplace (`app/models/marketplace.py`, `app/payments.py`) is a fully separate,
  disconnected system: `MarketplaceItem.price_cents`/`currency` and
  `MarketplaceOrder.price_cents`/`payment_provider`/`payment_reference` live directly on those
  rows — no shared ledger, no link to `usage_ledger`. Payments is already an adapter
  (`PaymentProvider` protocol, `none`/`stub` providers) following the same two-value
  `Literal["none", "stub"]` convention used elsewhere in `Settings`
  (`reconstruction_provider`, `mesh_generation_provider`, `signin_delivery`, ...) — this
  project already has a house style for "not built yet" integrations, which the credits
  payment/top-up side should follow rather than inventing a new pattern.

**Net assessment:** the audit's "zero infrastructure" is true for *prepaid credits,
enforcement across the real job pipeline, and admin-configurable pricing*. It is not true for
*ledger architecture* — `usage_ledger` already is the append-only, derivable-balance table
requirement 1 asks for. The job here is mostly **extend an existing, correctly-shaped system
to more call sites**, not design a new one from scratch.

## 2. Decision

1. **One ledger, not two.** Generalize `usage_ledger`/`services/usage.py` to be the system of
   record for all credit consumption (AI, compute jobs, marketplace digital downloads paid in
   credits). Do not create a parallel `credit_ledger` table — it would duplicate exactly the
   append-only/derived-balance machinery that already exists and is already proven (T-010).
2. **Balance stays derived, never a mutable counter.** Keep `SUM(credits_delta)` as the source
   of truth. If read-latency at scale later demands it, add a *cache*, refreshed from the
   ledger, never a value anything other than the ledger writes to directly.
3. **Meter by job, not by handler call, and dedupe on `job.id`.** The runner already has one
   choke point — `app/jobs/runner.py::_execute` — where every job's terminal outcome
   (`succeeded`/`failed`/`canceled`) is already decided. That is the metering seam.
4. **Charge on success, not pre-charge-and-refund.** `ai_commands.record_usage` already posts
   its ledger row *after* the provider call completes, with the real cost, not an estimate.
   Keep that pattern platform-wide: a canceled, failed, or paused-then-abandoned job posts
   zero ledger rows — no refund logic needed, because nothing was ever pre-debited. A
   pre-flight *balance check* (read-only, no write) still runs before expensive jobs start, so
   an empty-balance workspace fails fast instead of burning 20 minutes of Shap-E compute for
   nothing — but that check never itself writes to the ledger.
5. **Fail-open before fail-closed.** `ai_commands.enforce_budget` is already fail-closed today
   for the one path it covers. Every *newly* metered job type should launch in shadow mode
   (ledger row written, nothing blocked) before any enforcement flag is flipped — the data a
   shadow period produces is also what the owner needs to set real prices later.
6. **Pricing is versioned product policy.** The first safe implementation is a code-reviewed,
   immutable catalogue version used only for shadow quotes. A later
   `credit_price_rules` table (action type → credits per unit, versioned by
   `effective_from`) replaces the `Settings` env-var pattern for anything owner-adjustable.
   Each ledger row should snapshot which price rule it used (`price_rule_id`), so a later price
   change never silently rewrites historical cost attribution.
7. **Keep marketplace cash payments separate from credit consumption, joined by job/order id.**
   Real-money flows (`MarketplaceOrder`, future creator payouts) have different compliance
   requirements (currency, tax, money transmission) than credit metering. Recommendation:
   leave `MarketplaceOrder` as the system of record for cash transactions; if/when the owner
   allows paying for a listing *in credits* instead of cash, that posts a normal
   `usage_ledger` row (kind=`credits`, negative `credits_delta`) tagged with the order id in
   `metadata_`, exactly like a job's cost is tagged with `job_id` today. One consumption
   ledger; a separate, adapter-based cash ledger; joined by foreign ids, not merged into one
   schema.

## 3. Data model (concrete, phase-1-sized)

Extend `usage_ledger` rather than replace it:

- `idempotency_key` (text, unique per `(workspace_id, idempotency_key)` where not null) —
  metering a job posts with `idempotency_key = f"job:{job.id}"`; a retried attempt on the same
  job row is a no-op insert (`ON CONFLICT DO NOTHING` or a caught unique-violation), so
  `attempts` going from 1→2→3 on the same `Job` never double-charges. This mirrors the
  existing `uq_jobs_workspace_idempotency` constraint's purpose one layer up.
- `action_type` (text or a widened `UsageKind`) — today `kind` is a short fixed enum
  (`ai_tokens`, `gpu_seconds`, ...). Metering needs to distinguish *billable action*
  (`generate_mesh`, `slice_preview`, `marketplace_download`, ...) from *resource kind*
  (tokens, GPU-seconds). Cheapest correct move: keep `kind` for resource/unit as-is, add
  `metadata_["action_type"] = job.type` (already how `ai_commands.record_usage` tags
  `operation`/`provider`/`model`) — no schema change needed for phase 1, since `metadata_` is
  already JSONB and already used this way.
- `price_rule_id` (nullable FK, added in phase 3 only, once `credit_price_rules` exists) — so a
  priced ledger row is traceable to the exact rule applied.
- New table, phase 3: `credit_price_rules(id, action_type, unit, credits_per_unit, plan_tier
  nullable, effective_from, created_by, created_at)`. Versioned, never mutated in place —
  changing a price inserts a new row with a later `effective_from`; the metering code reads
  "the rule effective now for this action_type/tier." This is the admin-configurable surface
  requirement 3 asks for, deliberately shaped like `ProjectVersion`'s own
  immutable-version-over-mutation convention already used elsewhere in this codebase.
- New column, phase 3: some notion of platform-admin. Does not exist today; smallest viable
  version is a boolean/enum on `User` (mirroring how `plan` already lives there) gated by a
  new dependency in the API layer — but this is itself a small security-sensitive subproject,
  not a one-line add, and should be scoped and reviewed on its own.

## 4. Metering hook into the job pipeline

Add one method to `JobContext` (`app/jobs/runner.py`), next to the existing
`progress`/`pausable_checkpoint`/`check_still_wanted`:

```
def meter(self, action_type: str, quantity: Decimal, unit: str, *, cost_usd: Decimal = ZERO) -> None:
    ...
```

Call it from `_execute()` only in the `else: jobs.succeed(...)` branch — i.e. only on a
confirmed terminal success, using the already-unique `job.id` as the idempotency key. This
needs no new exception type and does not touch the existing `JobFailureError` /
`JobCanceledError` / `JobPausedError` control flow at all, so cancellation, pause/resume, and
retry semantics are completely unaffected by adding metering.

**Fail-open vs. fail-closed, per phase:**
- Phase 1/2 shadow mode: `meter()` writes the ledger row; if the write itself fails (DB issue),
  log and continue — a missed ledger row is a backfillable gap, not a reason to fail a job the
  user already paid compute cost for.
- Phase 2 enforcement (once the owner decides which actions are billable, see §8): a
  **pre-flight, read-only** balance check before the handler runs, gated by a `Settings` flag
  per job type (so it can be enabled one job type at a time, matching how
  `mesh_generation_provider`/`reconstruction_provider` are already toggled per-feature rather
  than globally). Recommend fail-closed only after a shadow-mode bake-in, exactly as T-047's
  existing budget guard already does for AI commands today — don't invent a different default
  for the rest of the pipeline.
- Partial completion/cancellation: no refund mechanism is needed under the charge-on-success
  design (§2.4). This is simpler than pre-charge+refund and is already the pattern
  `ai_commands.record_usage` and `diagnose_print.py` use.

## 5. Staged implementation plan

Each phase is independently shippable and sized for one coder subagent pass.

**Phase 1 — ledger generalization, shadow metering, no enforcement.**
*Not blocked on any owner decision — can start immediately.*
- Migration: add `idempotency_key` (nullable, unique-when-present) to `usage_ledger`.
- Wire `usage.record()` into every job handler currently uncharged (`generate_mesh`,
  `reconstruct_scan`, `print_jobs.py`'s three handlers, `export_job`, `facade`, `furniture`,
  `site_plan`, `house_box`/`house_walls`, `thumbnail`, etc.), writing real `cost_usd`/`quantity`
  where derivable (CPU/GPU seconds, output size) and `credits_delta=0` for now — informational
  only, nothing blocks.
- Expose a `GET` balance/usage endpoint generalizing the pattern already in
  `app/api/ai_commands.py` (`budget_usd`/`remaining_usd`), reusing
  `usage.workspace_totals()` unchanged.
- No new tables beyond the idempotency column; no admin role; no pricing table.

**Phase 2 — enforcement (fail-closed gating), per job type.**
*Partially blocked — see §8. The wiring (the `meter()`/pre-flight-check mechanism itself) can
be built and tested now; actually turning enforcement on for any given job type needs the
owner's answer to "is this action billable and at what rough cost shape" first.*
- Add `JobContext.meter()` and the pre-flight balance check described in §4.
- Add a per-job-type `Settings` enforcement flag (env-var, same convention as today — no
  pricing table needed yet, since phase 2 can run on the existing USD-budget-ceiling model).
- Decide and implement the "insufficient balance" UX: reject the job at submission (cleanest,
  consistent with how `ai_commands.enforce_budget` already raises before a job is even
  created) rather than queuing then failing it.

**Phase 3 — admin-configurable pricing.**
*Blocked on owner decisions in §8 (pricing model, tiers) plus a new platform-admin authz
primitive that doesn't exist yet and should be scoped separately.*
- `credit_price_rules` table + `price_rule_id` on `usage_ledger`.
- Minimal platform-admin role/authorization.
- Admin UI/API to create/version price rules per action type and plan tier.
- Metering switches from USD-budget-ceiling to actual credits-per-action pricing.

**Phase 4 — real money: top-ups and marketplace unification.**
*Blocked on owner decisions in §8 (payment processor, currency, payout mechanics, legal/
compliance for money transmission).*
- A `PaymentProvider`-style adapter (same shape as `app/payments.py`) for credit top-up
  purchases, posting positive `credits_delta` rows.
- Optional: let a marketplace listing be payable in credits, posting a tagged `usage_ledger`
  row as described in §2.7, while `MarketplaceOrder` remains the record for cash payments.
- Creator payout ledger — likely its own table, not forced into `usage_ledger`, since payouts
  are money *owed to* someone, not consumption.

## 6. Explicitly NOT decided here (owner-only, blocks phase 2+)

- Final enforced credit cost per action type. Version `2026-10-29.v1` is now the published shadow
  quote catalogue; changing it requires a new version and tests, and it does not debit balances.
- Subscription/plan tiers and what each includes.
- Free-tier size (credits granted on signup, if any, and renewal cadence).
- Currency for purchasing credits, and conversion rate (credits ↔ currency ↔ USD cost).
- Payment processor choice for top-ups (phase 4).
- Creator payout mechanics and percentage split (phase 4, also F-004's own open scope).
- Whether credits expire, and refund policy beyond the engineering no-refund-needed mechanism
  in §2.4 (e.g., does support ever manually credit a workspace — yes, trivially, by posting a
  positive `credits_delta` row with a human-readable `metadata_` reason; that capability
  exists the moment phase 1 ships, no further engineering needed for it).
- Who is a "platform admin" and how that's granted (phase 3 prerequisite, itself a small
  security-sensitive decision, not just a pricing one).

**Phase 1 is deliberately scoped to need none of the above.** It only adds visibility
(shadow metering + a read endpoint) to a ledger design that already exists and is already
correct for this purpose. Phases 2–4 each name their specific blocking decision above; none
of them should start before that decision lands, to avoid building enforcement or pricing UI
around guesses that get thrown away.
