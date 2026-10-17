# ADR: F-018 Realtime Collaboration — Closing the Remaining Gap

- Status: Proposed
- Date: 2026-10-17
- Author: architect (subagent), for owner review
- Scope: F-018 (realtime collaboration) only. Does not reopen facade/roof/material/mobile-CAD
  increments tracked elsewhere in `docs/IN_PROGRESS.md`.

## Context

F-018 asked for realtime collaboration. What exists today, verified by reading the code, not
just the docs:

- **Live room** (`services/api/app/live.py`, `services/api/app/api/live.py`): one WebSocket per
  project (`/projects/{id}/live`). Presence (name/colour/session), cursor broadcast, notes pinned
  to a 3D point, and a 2-second poll that announces whenever `project.head_version_id` changes —
  regardless of what produced the new version (AI command, manual edit, worker job). Relaying goes
  through a `Broker` protocol: in-process `MemoryBroker` for one API instance/tests, `RedisBroker`
  (pub/sub + TTL-scored sorted set for presence) for multi-instance deployments. This is a solid,
  already-generalized transport — any future realtime signal can ride the same room without
  touching producers.
- **Edits remain immutable versions** (`services/api/app/models/versioning.py`): `ProjectVersion`
  has a `parent_version_id` and a `sequence_no`; nothing is mutated in place. The live room's own
  docstring states the model precisely: *"two people changing the model at once branch rather
  than overwrite."* Every edit job (`manual_edit.py`, `execute_plan.py`, `facade.py`, etc.) replays
  a full operation stack through the kernel (`kernel_exec.run_plan`) and produces a brand-new
  version with a complete new `Operation` log — there is no incremental "patch" path anywhere in
  the kernel boundary.
- **Plan annotations already have a working fine-grained concurrency model**
  (`services/api/app/api/plan_annotations.py`, `packages/contracts/src/floor-plan.ts`): a single
  JSONB array per `(project, plan)`, written with compare-and-swap on a `revision` column
  (`ON CONFLICT ... WHERE revision = base_revision`). On a 409, the client (web and mobile both,
  via `mergeAnnotationChanges`) does a three-way merge **per annotation id**: unchanged-on-one-side
  wins the other side, both-sides-same wins trivially, true conflicts keep the local value and
  surface the id. This is, in effect, an LWW-map CRDT at the granularity of "one annotation
  object" — no vector clocks, no field-level merge, and it works precisely because annotations are
  independent, coarse-grained, user-owned objects with low write concurrency (a handful of people
  sketching on one plan).
- **Mobile presence/cursor/note parity is already implemented**, contradicting the premise in this
  task's brief. `apps/mobile/app/project/[id].tsx` sends `liveRoom.current?.pointAt(point)` and
  `liveRoom.current?.note(...)` and renders `liveCursors`/`liveNotes`/`liveColours` from the same
  WebSocket contract as web (`packages/contracts/src/live.ts`) — same endpoint, same message
  schema, no separate mobile path. This landed in commit `3ef0034` (2026-10-09, "build adaptive
  editor workspace"). `plan_annotations` sync followed on 2026-10-10 as *"another branch of the
  already-open live-room WebSocket"* (`docs/IMPLEMENTED.md`, 10.10.2026 entry) — not a second
  connection. What is **not** done, per that same changelog entry, is physical-device acceptance:
  two real devices concurrently, offline→reconnect, app-kill mid-edit. That was verified only by
  adversarial code trace, not hardware. That is a QA/acceptance gap, not an architecture gap.

What genuinely does not exist: merging two people's **concurrent fine-grained edits to the same
B-Rep feature tree or mesh** into one result. Today that produces two sibling versions (a branch),
with no automatic reconciliation.

## Decision

**Do not build OT or CRDT merge for the B-Rep feature tree or mesh edits.** Keep and strengthen
the immutable-version-branching model for geometry; invest instead in conflict *visibility* and
*resolution UX* at the version-branch level. Continue using the existing CAS+three-way-merge
pattern (already proven on plan annotations) as the template for any other collaborative surface
that is genuinely append/update-of-independent-objects shaped — it is a lightweight CRDT-by-
convention, not a gap to fill with a library.

Treat the stated mobile presence/cursor/note gap as **already closed in code**; the remaining work
there is physical-device acceptance testing, not implementation.

### Why OT/CRDT does not fit the B-Rep/mesh surface

OT and CRDT both assume the editing operations are small, independent, and commute (or can be
made to commute) cheaply — true for text (insert/delete at an offset) and reasonable for some
structured documents (Automerge/Yjs maps and sequences). None of that holds here:

1. **Operations are not independent — they are an ordered, dependency-heavy pipeline.** A B-Rep
   feature tree operation (boolean cut, fillet, loft) takes the *topology produced by every prior
   operation* as its input. `manual_edit.py` and `edits.build_stack_plan` don't patch a tree in
   place — they rebuild the entire stack through the OpenCascade kernel from scratch. There is no
   cheap "transform operation B to apply after A" step the way OT defines it for text; the "cost
   of transform" in CAD is a full exact-geometry recompute (seconds, not microseconds), and it can
   fail outright (invalid topology, self-intersection, OCCT exception) in a way an OT text-insert
   never does. A merge algorithm that must sometimes answer "these two trees cannot be reconciled,
   recompute failed" isn't OT or CRDT anymore — it's exactly the branch-and-choose model that
   already exists.
2. **Stable identity across concurrent structural edits doesn't exist for free.** The repo's own
   facade/material work had to solve this deliberately and non-trivially (stable `wall`/`roof`/
   `opening-frame` keys that "survive rebuild", explicit rule that a deleted role loses its
   assignment rather than silently migrating to another OCCT face). CRDTs need a stable identity
   per mergeable unit; here that identity is a hard-won, per-feature-family invariant, not a given.
   A general CRDT merge would have to re-litigate that problem for every operation type in
   `app/jobs` (currently ~20 job handlers, each with different params/entity_refs shape).
3. **Text-CRDT libraries are the wrong shape.** Yjs/Automerge give you sequences, maps, and text —
   not "two exact boolean cuts on the same face, reconciled by solid geometry." Adopting one would
   only help if the feature tree were re-modeled as the CRDT's native types, at which point you've
   thrown away the kernel-replay model that the rest of the product (thumbnails, exports, print
   checks, provenance, rollback-by-expression) already depends on.
4. **Concurrent fine-grained edits to the same body are rare in practice, and the existing UX
   already has an answer.** One editor "has the model open" per meaningful editing session in the
   common case; the live room already shows presence and cursors, so collaborators *see* someone
   else is in the body before they commit a conflicting op. The real failure mode is "I edited,
   someone else edited at the same time, now there are two versions" — a notification/merge-UX
   problem, not a missing merge algorithm.
5. **It would regress something the product relies on.** `provenance` JSONB on every version and
   the trusted-lineage checks used throughout (facade edits require a proven `house_box` lineage;
   `rollback` resolves "two hours ago" to a specific version; owner-handoff copies the *entire*
   immutable version graph) all assume one version has exactly one parent and one clear origin. A
   true merge operation would need *two* parents (a merge commit), which none of lineage
   validation, rollback-by-expression, or handoff currently models. Retrofitting two-parent
   lineage everywhere those checks live is a much bigger, riskier change than the UX work below —
   for a problem (simultaneous fine-grained CAD edits to the same body by two people) that the
   product's own usage pattern makes rare.

**Verdict on item 5 of the objective (what's not worth building):** full OT/CRDT merge of the
B-Rep/mesh editing surface is exactly that — not worth building. The immutable-version-branching
model is a deliberate, good fit for CAD semantics and the audit trail the rest of the product
depends on (thumbnails, print checks, rollback, handoff, trusted lineage). Building real merge
there would be a regression risk for a rare case, not a product improvement.

### What actually is worth doing

The plan-annotation CAS+merge pattern already demonstrates the right level of ambition for
*this* codebase: merge independent, coarse-grained, identified objects; let true conflicts surface
rather than silently resolving them; keep it server-authoritative with an optimistic revision
check. The gap is that this pattern exists only for plan annotations — not for version branches,
not for scene-graph-level concurrent edits (two people moving different furniture items, say).

## Options Considered

| Option | Fit | Verdict |
|---|---|---|
| OT on the B-Rep operation list | Needs cheap commuting transforms; CAD ops don't commute, recompute is expensive and can fail | Rejected |
| CRDT (Yjs/Automerge) wrapping the feature tree | Wrong native shape (text/sequence/map vs. exact kernel ops); would require re-deriving all job semantics on top of it | Rejected |
| CRDT applied only to scene-graph membership (which nodes exist, visibility, transform) while kernel ops stay versioned | Plausible for the *scene graph* layer (groups/instances/visibility/transforms already closed per `docs/IN_PROGRESS.md`'s "Mobile scene hierarchy" item) since that's closer to a map-of-objects shape | Deferred — not yet justified by a concrete concurrent-use complaint; revisit if/when real multi-editor sessions show scene-graph thrashing |
| Keep immutable-version branching; invest in conflict UX + extend CAS/three-way-merge pattern to other independent-object surfaces | Matches existing architecture, lowest risk, reuses a pattern already shipped and load-bearing | **Recommended** |

## Staged Plan

Each phase ships and is testable independently; a coder subagent can take one phase at a time.

### Phase 1 — Conflict visibility for version branches (no schema changes to geometry)
- When the live room's `watch_head` detects a new head that did **not** descend from the version
  the current client was looking at (i.e., `parent_version_id` diverges from what the client last
  saw), surface a distinct event (e.g. `{"type": "branch", ...}`) instead of just `{"type":
  "version", ...}`. The room already knows the prior head (`last` in `watch_head`); this is a
  comparison against stored lineage, not new infrastructure.
- Web/mobile: show "someone else published a version while you were editing — you're on a branch"
  with a link to both versions and a diff-of-thumbnails (the parent↔current render-crop compare
  already shipped for facade editing, per `docs/IN_PROGRESS.md`, generalizes here).
- Test: two sessions open the same project at the same head, each finalizes a version; the client
  that finalized second (or just observes) gets the `branch` event with both version ids.

### Phase 2 — Named/comparable branches + manual reconciliation action
- Let a user explicitly mark a branch for comparison against another sibling (reuse
  `VersionComment` / the existing versions feed UI — no new table needed if provenance already
  carries `parent_version_id`).
- Add one user-initiated action: "continue from the other branch" (re-apply *my* recent operation
  stack as a new child of the sibling's head) — this is just `manual_edit`'s existing
  `build_stack_plan`/`build_replacement_plan` replay machinery pointed at a different parent. It is
  explicitly a replay-and-recompute, not a merge; if the kernel rejects it (invalid topology), the
  user sees that like any other failed edit job today.
- Test: branch A adds a box, branch B adds a different box from the same parent; user picks
  "continue B's edits on top of A's head," gets a new version whose kernel recompute either
  succeeds or fails exactly like a normal edit job failure would.

### Phase 3 — Extend the CAS+three-way-merge pattern to one more independent-object surface
- Candidate: scene-graph-level concurrent edits (e.g., two people moving different furniture items
  or toggling different node visibility at the same time) — same shape as plan annotations:
  independent objects keyed by stable `SceneNode.id`, revision-guarded PUT, three-way merge by id
  on conflict.
- Do **not** generalize this into a shared library prematurely; copy the plan-annotations pattern
  once more, see if a third use case shows up before abstracting.
- Test: same adversarial pattern already used for plan annotations (two concurrent PUTs, 409,
  merge, verify independent changes both land and genuine same-id conflicts surface rather than
  silently dropping one side).

**Explicitly out of scope / not recommended for any phase:** OT or CRDT merge of B-Rep operations
or mesh geometry; a second realtime transport for mobile (none needed — parity already exists);
re-modeling the feature tree on a general-purpose CRDT library.

## Consequences

- No change to the trusted-lineage model: every version still has exactly one parent. Phase 2's
  "continue from the other branch" produces an ordinary single-parent child version via the
  existing replay path — it does not introduce two-parent merge commits.
- `live.py`/`live.py` (API) broker protocol is untouched; Phase 1 only adds a new message `type`
  on the same channel.
- Primary risk: Phase 2's "continue from the other branch" UX could confuse users if surfaced
  without a clear mental model ("this is a rebase, not a merge — it may fail"). Mitigate with
  explicit copy, not more backend logic.
- Mobile needs no new protocol work for presence/cursor/notes — that gap is closed. The owner
  should update whatever audit or ticket asserted otherwise; the remaining item is a physical
  two-device + app-kill acceptance pass, tracked already in `docs/IN_PROGRESS.md`.
