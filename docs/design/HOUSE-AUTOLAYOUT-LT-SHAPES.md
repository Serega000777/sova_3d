# House auto-layout for L/T contours (design)

Status: implemented on 2026-10-11. Picks up item 13 in `docs/COMPETITOR_UI_ANALYSIS.md`'s
"Полный сценарий Sova 01–20" table ("Дом с нуля: контур, стены, проёмы и автоплан",
line 117: "Контур дома, server plan и автокомнаты/двери работают для прямоугольника;
L/T/free-form auto-layout, этажи и отдельный mobile plan screen не сделаны") and the
matching ledger entries — `docs/IMPLEMENTED.md:62` ("Г-/Т-/произвольные контуры честно
отклоняются до отдельного layout engine") and `docs/IN_PROGRESS.md:140` ("для Г-/Т-/
произвольных контуров и ручной геометрической правки плана ещё нужен отдельный layout
engine"). This has been deferred across multiple ledger entries without a design pass;
this is that pass, grounded in reading `services/api/app/engineering/floor_plan.py`,
`house_box.py`, `house_walls.py`, `services/api/app/services/floor_plans.py`,
`services/api/app/api/floor_plans.py`, `services/api/tests/test_floor_plan.py`, and
`apps/mobile`'s plan-related sources directly — not from memory of what they probably
contain.

## 0. What exists today, exactly

`floor_plan.py`'s `auto_layout_rectangular_plan` (lines 131–225) is the only auto-layout
path. It:

1. Calls `_rectangular_bounds` (lines 106–128), which takes every point across
   `plan.rooms[*].outline`, computes the axis-aligned bounding box, and **rejects unless
   the shoelace area of the rooms exactly equals the bounding-box area** (`rel_tol=1e-9,
   abs_tol=1.0`). This is the real gate: an L or T contour's room area is strictly less
   than its bounding box's area (the notch is missing), so this check raises
   `"automatic room layout currently requires an axis-aligned rectangle"` before anything
   shape-specific runs.
2. Picks the longer bounding-box axis and cuts `room_count` (2–8) equal strips
   perpendicular to it ("equal-strip"), each ≥ 2000 mm along that axis.
3. Requires exactly 4 exterior walls (walls whose fixed coordinate sits on the bbox
   min/max) — this check exists but is **not actually what blocks L/T shapes**: an
   L-contour's 6 walls still include exactly 4 that touch the bbox boundary (the 2
   notch-forming walls are interior), so this check alone would pass an L-shape. The
   shoelace check in step 1 is what fails first.
4. Adds one partition wall + one centred door per cut, all at `partition_thickness_mm`
   / `door_width_mm`, and returns a new `FloorPlan` with `rooms`/`walls`/`openings`
   replaced.

`house_box.py`'s `l_shape` and `t_shape` (and `floor_plan.py`'s matching outlines,
lines 61–81) are fixed-proportion examples, not the only L/T shapes that can exist:
`house_walls.py` already accepts an **arbitrary** axis-aligned closed polygon (any
number of segments ≥ `MIN_WALLS = 3`, connected into one degree-2 cycle via
`ordered_wall_outline`) — so a hand-drawn L or T with different proportions, or a
notch in a different corner, already exists as valid plan data today. Auto-layout
rejects all of them identically, because the gate is "is this a rectangle," not
"is this a rectangle, L, or T."

## 1. Proposed algorithm: reflex-vertex decomposition, bounded to L and T

**Core idea: classify the contour by its reflex-vertex structure, decompose it into
exactly two axis-aligned sub-rectangles along one interior seam, run the existing
equal-strip algorithm independently inside each sub-rectangle, then stitch the two
sub-plans together with one connecting partition + door at the seam.** This reuses
100% of the existing per-rectangle logic (step 2 above) unchanged; the new code is the
classification, the cut, and the stitch.

### 1.1 Classification

A simple axis-aligned polygon's vertices are each either convex (90° interior angle)
or reflex (270° interior angle); a rectangle has zero reflex vertices. For an interior
angle to be well-defined every edge must be axis-aligned (already true for every
contour `house_box`/`house_walls` can produce — diagonal walls do not exist in this
codebase yet) and the polygon must be simple (already guaranteed by
`ordered_wall_outline`'s degree-2-cycle check).

- **L-shape = exactly one reflex vertex.** The reflex vertex's two incident polygon
  edges each lie on an axis-aligned line; the cut is the *continuation* of one of
  those lines **through** the reflex vertex, past it, in the direction away from the
  incident edge, until it meets the polygon's opposite boundary. It is **not** the
  incident edge itself — that edge already exists as exterior wall and terminates
  exactly at the reflex vertex, so retracing it touches the boundary rather than the
  interior and splits nothing. For the `house_box` L, the reflex vertex is
  `(length/2, width/2)`, with incident edges running to `(length, width/2)` and
  `(length/2, width)`; the two valid interior chords are
  `(length/2, width/2)`–`(0, width/2)` (continuing the `y = width/2` line leftward,
  past the reflex vertex, to the far boundary at `x = 0`) and
  `(length/2, width/2)`–`(length/2, 0)` (continuing the `x = length/2` line downward
  to the far boundary at `y = 0`). Each is new interior geometry — confirmed by
  checking that no point strictly between its endpoints coincides with an existing
  wall — and either splits the polygon into exactly 2 rectangles whose combined
  shoelace area equals the original footprint's; pick the one whose seam gives the
  more balanced area split on ties. Unlike the T-shape case below, this chord's far
  endpoint (`(0, width/2)` or `(length/2, 0)`) generally falls in the *middle* of an
  existing exterior wall rather than on an existing vertex, so that one wall must be
  split into two collinear segments at the seam endpoint during stitching (§1.4).
- **T-shape = exactly two reflex vertices that are collinear along one axis, with the
  straight interior segment between them lying entirely inside the polygon.** For the
  `house_box` T, the reflex vertices are `(third, 2·width/3)` and `(2·third, 2·width/3)`
  — same y, and the segment between them is the stem/bar seam. Connecting them directly
  is the cut; it splits the polygon into exactly 2 rectangles (`stem`: the narrow
  bottom rectangle; `bar`: the full-width top rectangle, which also spans over the two
  side notches that are outside the stem but still exterior-adjacent at the bar's
  height).
- Both rules are rotation/mirror-invariant and **proportion-invariant** — they accept
  any axis-aligned L or T, not just `house_box`'s fixed thirds/halves, including
  hand-drawn ones via `house_walls` with the notch in any corner or the stem attached
  at any offset along its edge (as long as the two reflex vertices are collinear; see
  §2 for when they are not).

### 1.2 Room-count distribution across the two sub-rectangles

Reuse the existing `room_count` parameter (2–8) rather than adding a new one. Split it
across the two sub-rectangles proportionally to their area:

```
area_total = area_a + area_b
room_count_a = max(1, round(room_count * area_a / area_total))
room_count_b = room_count - room_count_a   # remainder, not re-rounded, so totals match exactly
```

If `room_count_b < 1`, move one room from `a` to `b` (and symmetrically). This keeps
the invariant "every requested room exists exactly once" without reintroducing
rounding drift, mirroring the existing code's preference for exact, checkable
arithmetic over approximation.

### 1.3 Per-zone equal-strip (refactor, not reimplement)

`auto_layout_rectangular_plan`'s core loop (lines 185–221) currently derives its
bounding box from the *whole* plan via `_rectangular_bounds`. Factor that loop into a
helper that takes explicit `(min_x, min_y, max_x, max_y, room_count)` instead of
deriving them from a plan, so both the existing single-rectangle path and the new
per-zone calls share one strip-cutting implementation. No behavior change for the
existing rectangle path — same inputs, same outputs, same 2–8/2000mm/door-width
validation, just called with explicitly-supplied bounds.

### 1.4 Stitching

1. **L-shape only**: the seam chord's far endpoint (e.g. `(0, width/2)`) generally
   lands in the middle of one original exterior wall rather than on an existing
   vertex. Split that one wall into two collinear `PlanWall`s at the seam endpoint,
   one assigned to whichever zone it borders; every other original exterior wall is
   unchanged. (The T-shape never needs this step — both its seam endpoints are
   already existing polygon vertices, so each zone's boundary is a clean subset of
   the original walls with no mid-wall split.)
2. Run the refactored strip-cutter once for zone A's bounds with `room_count_a`, once
   for zone B's bounds with `room_count_b`. Each call returns its own rooms + internal
   partitions + doors, numbered from 1.
3. Renumber B's rooms to continue after A's (`Room {room_count_a + i}`).
4. Add **one** partition wall along the seam chord, at the same `partition_thickness_mm`
   as every other partition. Before adding its connecting door, collect every point
   where an internal strip partition from either zone touches/crosses the seam and
   project those points to scalar offsets `p` along the seam from endpoint A. A strip
   partition ending at the seam is an intentional T-junction, but its solid wall must
   not land inside the seam door opening.
5. Place the seam door with this deterministic collision-free rule (all distances are
   along the seam centreline):
   - use `SEAM_DOOR_CLEARANCE_MM = 200`, matching the existing `door_width + 400`
     minimum-length discipline;
   - begin with the usable seam interval `[200, seam_length - 200]`;
   - for every strip-partition intersection at offset `p`, subtract
     `[p - (partition_thickness_mm / 2 + 200),
     p + (partition_thickness_mm / 2 + 200)]`. This accounts for the partition's
     physical half-thickness and leaves 200 mm of clear wall between its face and the
     door edge;
   - discard every remaining interval shorter than `door_width_mm`. If none remains,
     reject with `"the seam has no collision-free span for the requested door width"`;
   - in each remaining interval, clamp the normally-centred door start
     `(seam_length - door_width_mm) / 2` to that interval's legal start range. Choose
     the candidate whose centre is closest to the seam midpoint; break an exact tie by
     the smaller offset from seam endpoint A. Thus the door stays centred when that is
     safe and moves only as far as needed when a strip partition blocks the centre.
   This one door keeps the house a connected room graph: because its whole span lies
   strictly between partition intersections, it opens from exactly one room in zone A
   into exactly one room in zone B.
6. Concatenate A's exterior walls, B's exterior walls, both zones' internal
   partitions, the seam partition, and all openings (remapping `wall` indices as the
   existing code already does for the outer-wall remap at lines 178–184) into one
   `FloorPlan`.

Both zones' exterior walls, taken together, already equal the original L/T polygon's
exterior boundary minus the seam — no new exterior-wall *line* is invented, only the
seam itself and (for the L-shape) the one wall-split from step 1 above.

The two canonical collision cases show why step 5 is required and provide exact
regression fixtures:

- **L, 12,000 × 8,000 mm, 5 rooms.** The 6,000 × 4,000 upper zone gets 2 rooms and
  cuts at `x=3000`; the 12,000 × 4,000 lower zone gets 3 rooms and cuts at `x=4000`
  and `x=8000`. The seam is `x=0…6000` at `y=4000`, so the first two cuts touch it.
  A centred 900 mm door occupies physical `x=2550…3450` and is bisected by the
  `x=3000` partition. With a 120 mm partition and the rule above, each crossing has a
  `60 + 200 = 260` mm exclusion radius. For seam orientation `(6000,4000) →
  (0,4000)`, the selected door offset is `3260…4160`, i.e. physical
  `x=1840…2740`; its nearest partition is 260 mm beyond the door edge.
- **T, 12,000 × 8,000 mm, 4 rooms.** The 12,000 × 2,666.67 bar gets 2 rooms, so its
  partition ends on the seam at `x=6000`; the 4,000 × 5,333.33 stem also gets 2 rooms
  but its partition is parallel to the seam. The centred 900 mm seam door would occupy
  `x=5550…6450` and be bisected at `x=6000`. For seam orientation
  `(4000,5333.33) → (8000,5333.33)`, the tie-break selects offset `840…1740`, i.e.
  physical `x=4840…5740`, again leaving exactly 260 mm to the partition centreline.

## 2. Fail-closed boundary

Same discipline as the existing rectangular path and as the exact-facade work
(`docs/COMPETITOR_UI_ANALYSIS.md` item 16: "API fail-closed отклоняет неизвестные/
повторные keys/material ids, ... непрямоугольные дома"): **never guess a layout for a
shape the algorithm cannot prove correct for — reject with a specific reason instead.**

| Contour | Outcome |
|---|---|
| 0 reflex vertices (rectangle) | **Accepted** — unchanged existing path |
| Exactly 1 reflex vertex, chord continues an incident edge's line past the reflex vertex into the interior to the opposite boundary (not retracing an existing edge) | **Accepted** — L path |
| Exactly 2 reflex vertices, collinear, interior chord fully inside the polygon | **Accepted** — T path |
| Exactly 2 reflex vertices, *not* collinear (e.g. an off-axis T, a Z/S-shape, a plus-shape) | **Rejected**: `"this contour's reflex corners don't form a single L or T seam"` |
| 3+ reflex vertices (true free-form, crosses, staircases, zig-zags) | **Rejected**: `"automatic room layout currently supports rectangle, L and T footprints only"` |
| Any edge not axis-aligned (diagonal wall) | **Rejected** — already impossible to express via `house_box`/`house_walls` today, but guard explicitly since reflex-angle detection assumes orthogonality |
| Either sub-rectangle's split axis shorter than `room_count_zone × 2000mm` | **Rejected** — same message/threshold as the existing per-rectangle check, applied per zone |
| Seam chord shorter than `door_width_mm + 400mm` | **Rejected**: `"the seam between the two parts of the house is too short for the requested door width"` — same shape as the existing partition-length check |
| Seam passes the basic length check, but strip-partition exclusion bands leave no continuous interval at least `door_width_mm` long | **Rejected**: `"the seam has no collision-free span for the requested door width"` — never emit overlapping wall/opening geometry |
| Self-intersecting / disconnected / branching polygon | **Rejected** — already handled upstream by `ordered_wall_outline`, unchanged |

No shape in the rejected rows receives an approximated or "closest guess" layout. This
increment explicitly does **not** attempt true arbitrary free-form polygons (U-shapes,
crosses, staircase footprints, anything with 3+ reflex vertices or non-collinear reflex
pairs) — that remains the deferred "separate layout engine" the ledger already names,
and stays deferred after this increment ships. A general rectilinear-polygon minimum-
rectangle decomposition (reflex-vertex pairing via bipartite matching) is the right tool
for that later increment, but it is materially harder to make provably correct and to
explain to a user when it rejects a shape — scoping this increment to the two concrete
shape classes the table names keeps the "never guess" guarantee easy to verify by
reading the code, which L/3-reflex-vertex-and-up decompositions would not be.

## 3. Multi-floor: separate concern, not bundled

The table's cell also names "этажи" (floors), but it does not follow naturally from
this contour-decomposition work and should **not** be bundled into this increment:

- `FloorPlan` (and the `floor_plan` provenance key it lives in) is modeled as **one
  plan per project version**, not a list of per-floor plans. `HouseBoxRequest.floors`
  (1–3) already exists and changes the *massing box height*
  (`house_box.py` line 63: `height = floor_height_mm * floors`), but `floor_plan.py`
  only ever projects one footprint onto the ground plane — there is no floor index
  anywhere in `FloorPlan`, `PlanRoom`, `PlanWall`, or `PlanOpening`.
- Real multi-floor room layout needs floor-to-floor structural alignment (upper-floor
  partitions should usually land above a load-bearing wall or beam below, not float),
  a stair/shaft data model (a stair's footprint is a hole punched through *two*
  floors' room layouts simultaneously, not a room on one floor), and a decision about
  whether each floor gets an independent `room_count`/layout or must share one. None
  of that is answered by, or needed for, deciding how to cut an L or T contour into
  rectangles.
- Conclusion: **out of scope here.** Multi-floor auto-layout is a separate data-model
  increment (a `floors: list[FloorPlan]` shape, or similar) that this L/T work does not
  block and does not need to anticipate — the per-floor engine, once floors exist as a
  concept, can call the same per-rectangle/per-L/per-T decomposition this doc designs,
  once per floor.

## 4. Mobile plan screen: checked against current code, not stale

The table also names "отдельный mobile plan screen" for from-scratch house creation.
Checked directly rather than assumed:

- `apps/mobile/src/PlanAnnotator.tsx` and `apps/mobile/src/plan-sync.ts` (the mobile
  work landed since this gap was first identified, per `docs/design/MOBILE-PLAN-EDITOR.md`)
  are an **annotation editor for a plan that already exists** — pins/text/shapes/
  dimensions on top of a house a project already has. `apps/mobile/src/PlanViewer.tsx`
  renders rooms/walls/openings for the Plan↔Model split, also for an existing plan.
- Grepping all of `apps/mobile` for `house_box`/`HouseBoxRequest`/`house-box`/
  `house_walls`/any house-creation reference returns **nothing**. There is no mobile
  equivalent of web's `HouseBoxWizard.tsx` / `HouseWallsWizard.tsx` (the "define a
  contour, pick a shape, generate the massing box" flow) at all.
- Verdict: the table is **not stale** on this point. "Create a house from scratch and
  run autoplan on mobile" is a materially different screen from the shipped plan
  *editor* (annotate an existing plan) and the shipped plan *viewer* (view an existing
  plan's rooms/walls) — it is the mobile port of `HouseBoxWizard`/`HouseWallsWizard`
  plus a mobile trigger for `POST /projects/{id}/floor-plan/auto-layout`, none of which
  exists yet. This is real, separate, UI-only work (the API contract is already
  platform-agnostic, same pattern `MOBILE-PLAN-EDITOR.md` found for annotations) and
  deserves its own design pass the same way that document got one — **out of scope for
  this algorithm doc**, flagged here as the next natural design doc rather than
  bundled in.

## 5. API / provenance surface changes

No endpoint or request/response shape changes. `POST /projects/{id}/floor-plan/
auto-layout` keeps its existing body (`base_version_id`, `room_count`,
`partition_thickness_mm`, `door_width_mm`) — the shape classification happens
server-side, transparently, same as how the endpoint today doesn't ask the caller
whether their footprint is a rectangle.

One addition: `floor_plans.py`'s `auto_layout_project_floor_plan` currently tags every
generated version with `"floor_plan_layout": {"kind": "equal_strips_v1", ...}`
(services/floor_plans.py, the provenance dict literal). The L/T path must tag its
output with a **different** kind value (`"lt_decomposition_v1"`) carrying both zones'
room counts and the seam coordinates, so the version history/ledger stays honest about
which algorithm produced a given plan — exactly the same discipline the existing kind
field already enforces for the rectangle path, just with a second valid value instead
of the only value.

`auto_layout_rectangular_plan` gets renamed or wrapped (e.g. `auto_layout_plan`) to
dispatch on classification result: rectangle → existing path unchanged; L/T →
decompose-and-stitch; anything else → the fail-closed `ValueError`s from §2. Callers
(`floor_plans.py`) need no change beyond the provenance `kind` value and updated error
messages already bubbling through `ValidationFailedError`.

## 6. Touch list

- `services/api/app/engineering/floor_plan.py`:
  - Add reflex-vertex classification (`_classify_contour` or similar) operating on a
    single `PlanRoom.outline`.
  - Add the L and T decomposition (seam-finding) functions.
  - Refactor the strip-cutting core out of `auto_layout_rectangular_plan` into a
    bounds-parameterized helper (§1.3); keep `auto_layout_rectangular_plan` as a thin
    wrapper for the rectangle case so existing callers/tests referencing that name by
    exact signature keep working, or rename and update the one call site in
    `floor_plans.py` — pick whichever keeps the existing test file's rectangle-path
    assertions passing unchanged.
  - Add the stitching function (zone merge + seam partition + collision-free seam
    door placement from §1.4 steps 4–5; for the L-shape path, also the mid-wall split
    from §1.4 step 1 since the seam's far endpoint there is not an existing vertex).
  - Add the new top-level dispatcher.
- `services/api/app/services/floor_plans.py`: call the new dispatcher; branch the
  provenance `kind` value on which path actually ran.
- `services/api/tests/test_floor_plan.py`:
  - `test_auto_layout_refuses_irregular_or_impossibly_small_footprints` currently
    asserts the `house_box` L-shape is refused (lines 107–118) — this assertion is
    **expected to change** once this increment ships; replace it with an L-shape
    *acceptance* test, and add a new small-footprint/non-collinear-reflex rejection
    test to keep that guarantee covered.
  - New tests per §7 below.
- `docs/IMPLEMENTED.md` / `docs/IN_PROGRESS.md` / `docs/COMPETITOR_UI_ANALYSIS.md`
  item 13: update once implemented, same ledger discipline as every other shipped
  increment — note the row should then read "L/T auto-layout: done; free-form,
  floors, mobile screen: still open" rather than clearing the whole cell.

## 7. Proof plan

- **Classification unit tests**: rectangle → 0 reflex; `house_box` L → 1 reflex at the
  expected coordinate; `house_box` T → 2 collinear reflex vertices; a hand-drawn
  `house_walls` L with different proportions and the notch in a *different* corner →
  still classified L (proves proportion/rotation invariance); a hand-drawn plus/cross
  shape (4 reflex vertices) → rejected; an off-axis "T" where the two reflex vertices
  are not collinear → rejected with the specific non-collinear message.
- **Decomposition correctness**: for both `house_box` L and T, assert the two
  sub-rectangles' combined shoelace area equals the original polygon's area exactly
  (no overlap, no gap), and that every sub-rectangle vertex is axis-aligned and
  matches a hand-computed expected value (the exact coordinates worked out in §1.1).
- **End-to-end layout tests** mirroring `test_rectangular_house_gets_connected_rooms_
  and_internal_doors`: build an L-shape `FloorPlan`, call the new dispatcher with
  `room_count=4`, assert room count, total area equals source polygon area, every
  partition has exactly one door, and the seam partition/door specifically exist and
  are centred on the seam when no strip partition blocks the centred span. Repeat for
  T with `room_count=5` (uneven split across 2 zones) to exercise the remainder-
  distribution rule in §1.2.
  - Add exact collision regressions for the two fixtures calculated in §1.4: canonical
    L with 5 rooms must avoid seam crossings at `x=3000` and `x=4000`, and canonical T
    with 4 rooms must avoid the crossing at `x=6000`. Assert that the seam-door span
    neither overlaps any perpendicular partition's half-thickness nor violates the
    additional 200 mm clearance; also assert the deterministic offsets stated there.
  - Regenerate (increase/decrease `room_count`) on an already-auto-laid-out L/T plan,
    mirroring the existing rectangle test's two-call pattern (lines 92–104), to prove
    idempotent re-derivation from the same source footprint.
- **Fail-closed tests**, one per row in §2's table: non-collinear 2-reflex shape,
  3+-reflex shape, zone too small for its assigned room count, seam too short for the
  door width, and a seam long enough for the basic check but fragmented by strip
  partitions so no collision-free door interval remains — each asserting the exact
  `ValueError` message, same pattern as the existing
  `test_auto_layout_refuses_irregular_or_impossibly_small_footprints`.
- **API/contract level** (`services/api/tests/integration/test_house_box_api.py` or a
  new sibling): `POST /projects/{id}/floor-plan/auto-layout` against an L-shaped
  `house_box` project returns 201 with the new `kind: "lt_decomposition_v1"` in
  provenance; against a 3-reflex-vertex `house_walls` project returns the existing
  422/`ValidationFailedError` path, proving the fail-closed boundary holds through the
  full HTTP stack, not just the engineering-module unit tests.
- **Ledger gate**: full API test suite (currently "609 passed, 3 skipped" per
  `docs/IMPLEMENTED.md:62`) plus Ruff/mypy, same bar as every other shipped increment
  in this ledger.

## Summary

- **Algorithm**: classify the contour by reflex-vertex count/collinearity; decompose
  L (1 reflex vertex) and T (2 collinear reflex vertices) into exactly two axis-aligned
  sub-rectangles via one interior seam; run the existing equal-strip algorithm
  independently in each sub-rectangle with a proportional room-count split; stitch
  with one seam partition and place its connecting door in the collision-free span
  nearest the seam centre, failing closed if no span fits, so the result is one
  connected house without overlapping wall/opening geometry.
- **Shape-class scope boundary**: rectangle (existing, unchanged), L (1 reflex vertex),
  T (2 collinear reflex vertices) are accepted. Anything with 3+ reflex vertices, or
  exactly 2 non-collinear reflex vertices, or non-axis-aligned edges, is rejected with
  a specific reason — true arbitrary free-form stays explicitly deferred to a later
  increment, not attempted here.
- **Floors**: out of this increment — materially separate data-model work
  (`FloorPlan` has no floor index today; alignment/stairs/shafts are a different
  problem than contour decomposition).
- **Mobile plan screen**: out of this increment, and the table is **not stale** —
  mobile's shipped `PlanAnnotator`/`PlanViewer` work is for editing/viewing an
  *existing* plan, not for creating a house contour from scratch (no mobile
  `HouseBoxWizard`/`HouseWallsWizard` equivalent exists); this is a separate,
  UI-only design pass, flagged as the next natural follow-up.
