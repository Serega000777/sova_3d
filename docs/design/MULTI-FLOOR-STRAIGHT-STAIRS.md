# Item 26 — bounded multi-floor house and stairs

## Acceptance boundary

This increment turns `floors` from a visual height multiplier into explicit floor data for one
bounded creator: a rectangular `house_box` with two or three floors and one repeated straight
flight between adjacent levels.

It must produce, from the same immutable request:

- a separate exact floor shell for every level;
- one aligned opening in every upper floor;
- an exact fused step body for every floor transition;
- optional left/right sloped rail bodies;
- a separate flat-roof body;
- scene groups for every floor and the roof;
- one aligned 2D plan per floor with an `up` and/or `down` stair footprint.

The existing one-floor and shape-only rectangle/L/T house paths remain backward compatible.

## Repeated L/T multi-floor shells

A two- or three-floor house without a stair now stores every rectangle, L or T level as a
separate exact open-top shell at its measured elevation, plus a separate flat roof with the same
validated footprint. The immutable scene contains one group and one shell object per level, so
the existing visibility/cutaway controls work for non-rectangular houses too. The server stores
one aligned 2D plan per level instead of collapsing the request to a legacy single plan.

This path repeats the same footprint and floor height on every level. It does not infer stairs,
shafts, openings, setbacks or different upper-storey contours. One-floor requests keep their
historical single-body OperationPlan unchanged.

Web auto-layout can apply one room program (typed when composition mode is enabled) to every
stored floor. It calls the existing exact-floor endpoint sequentially, always using the immutable
version returned by the previous layout or furniture job as the next base. Each floor is still laid out and validated independently,
so its stair footprint and measured elevation remain authoritative. A later failure does not roll
back earlier immutable versions; the UI reports the completed-floor count and keeps the latest
successful version active. This is coordinated repetition, not a cross-floor structural optimizer:
it does not align partitions, wet stacks or load paths between levels.

Mobile's house scenario now offers the same direct typed creator in addition to the existing
read-only text proposal flow. It submits bounded rectangle/L/T dimensions, one to three floors,
and optional straight, L-turn, U-turn or winder-turn stairs only for a rectangular multi-floor house. The client checks
dimension, riser and L-stride bounds for immediate feedback; the API and worker still revalidate
the exact request before the immutable job is accepted and executed.

## Trusted contract

`HouseBoxRequest.stair` is optional and accepts only:

- width: 700–2000 mm;
- tread depth: 200–400 mm;
- step count: 10–30;
- placement: left, centre or right;
- railing on/off;
- an optional existing interior-material id.

The client does not submit a riser height. The server derives
`floor_height_mm / step_count` and rejects results outside 120–220 mm. It also derives the run,
checks 350 mm perimeter clearance, validates that the stair and shaft fit the footprint, and
rejects a stair for a one-floor or non-rectangular house. The material id is resolved from the
server-owned add-only catalogue before the job is accepted and again inside the worker job.

At the maximum accepted input (three floors, 30 steps, rails enabled), the generated plan has
137 operations, below the shared 256-operation ceiling. The first rejected step-count boundary
is 31.

## Exact geometry and immutable storage

Each floor is a `create_box` followed by an OCCT `shell` with an open top. Every upper shell is
cut by the same derived shaft footprint. Each stair tread is an exact box whose height is the
derived cumulative rise; boolean fuse operations produce one solid flight. Rails use exact box
bodies rotated about Y to the floor-to-floor slope. The roof is a separate exact box.

The job requires every declared output body from the geometry service, stores STL and B-Rep for
each body, attaches them to one immutable project version, and records every operation. Missing
kernel output fails closed before version finalisation.

The version's scene schema v2 contains root groups `floor_1_group` through `floor_3_group` as
needed plus `roof_group`. Stair and rail objects belong to their lower floor. Generic scene-tree
visibility therefore works per level; the project page's cutaway shortcuts create the same
immutable visibility-only child versions instead of mutating a browser-local view.

## Synchronized 2D plans

`GET /projects/{project_id}/floor-plans` returns `BuildingFloorPlans` for the current immutable
version. Each level has a unique plan id, zero-based index, elevation and full `FloorPlan`.
`PlanStair` carries the trusted floor link, footprint, width, run, step count, tread, derived
riser, railing and optional material. The web plan editor exposes floor tabs, renders the shaft,
treads and UP/DOWN direction, and keeps annotations isolated by plan id.

Historical versions without `floor_plans` deliberately return one legacy level. A previous
`floors` height multiplier is not reinterpreted as proof of separately modelled floors.

## L-turn follow-up (quarter-turn with landing)

`HouseBoxRequest.stair` is now a discriminated union on `kind`. Historical requests and plans
without a `kind` are read as `straight`, and the straight-stair `OperationPlan` is byte-identical
to the previous builder. `kind: "l_turn"` accepts only:

- width 700–2000 mm (the landing is a `width × width` square);
- tread depth 200–400 mm;
- lower and upper flight step counts 3–26 each;
- turn left (second flight climbs +Y) or right (−Y);
- placement left, centre or right across the house width;
- railing on/off and an optional existing interior-material id.

The API body forbids unknown fields, so a straight `step_count` sent with `kind: "l_turn"` is
rejected rather than ignored. The server derives `risers = lower + upper + 1` (the landing is one
riser), requires 10–30 risers and a 120–220 mm rise, applies the 550–700 mm `2 × rise + tread`
comfort rule, and places the whole L bounding box with the same 350 mm wall clearance. Any
failure is a 422 before a job is enqueued and is re-checked inside the worker job.

Per transition the plan builds every lower step, one landing box and every upper step as exact
boxes with cumulative heights, fused into `stair_<a>_<b>_step_1`. Each upper floor is cut by two
overlapping openings (lower flight + landing, then the upper flight) with the existing 50 mm
margin. Rails are six exact bodies: inner/outer sloped rails for both flights (rotate about Y and
X) and two horizontal guards on the landing's open outer sides. The maximum accepted request
(three floors, 30 risers, rails) is 153 operations; the first rejected riser count is 31.

`PlanStair` gains `kind`, `turn`, two `flights` (outline, step count, climbing direction) and a
`landing`; an L outline has six corners. Web parsing, translation and the plan editor's tread and
walking-line drawing use the shared `stairPlanLines` contract helper. Scene nodes keep the same
floor groups, so visibility and cutaway work unchanged. The existing auto-layout keeps rooms out of
the stair's whole bounding-box band.

Real OCCT 7.8.1 (`physical-ai-geometry:multifloor-shell`, no kernel source change since) executed
the 153-operation maximum plan and a two-floor right-turn plan: every floor, roof, flight and rail
body was a valid single solid, and each flight with its landing fused into one solid.

## Winder-turn follow-up (quarter turn with three winders)

`kind: "winder_turn"` joins two perpendicular flights with exactly three 30° winder treads around
an open `newel × newel` square. It accepts only:

- width 700–2000 mm, tread depth 200–400 mm, newel void 200–500 mm (strict finite numbers);
- lower and upper flight step counts 3–24 each (strict integers);
- turn left (+Y) or right (−Y), placement left/centre/right, an optional interior-material id;
- `railing: false` only.

Unknown fields are rejected. Every winder is one riser: `risers = lower + 3 + upper`, with the
shared 10–30 riser, 120–220 mm rise and 550–700 mm `2 × rise + tread` rules. The same stride rule
is also applied to the winders' going on one walking line, an arc of radius `newel + 300 mm` about
the newel's far corner (`going = radius × π/6`). Combined with the 200 mm newel minimum this makes
11 the smallest riser total that can actually pass. The footprint is
`(tread × lower + width + newel) × (width + newel + tread × upper)` and keeps the 350 mm wall
clearance; any setback additionally requires the opening to stay inside the smaller upper floor.

All four riser lines of the turn meet in the newel's far corner at 0°, 30°, 60° and 90°. With
`s = width + newel` the polygons are a quadrilateral, a six-point corner tread and a second
quadrilateral; their areas add up to `s² − newel²`, so nothing covers the newel. A right turn is
the mirrored left turn with the vertex order reversed back to counter-clockwise, so the prism
orientation never depends on the turn side. Before any plan exists the
layout must prove minimum edge length, winding, non-self-intersection, exact tiling and one whole
shared riser edge between every neighbouring pair, both flights included.

Per transition the plan emits one box per flight step, three polygon `extrude` prisms
(`stair_<a>_<b>_winder_1..3`) and fuses them into the single output `stair_<a>_<b>_step_1`. The
worker fails the job when the kernel does not report that output as one valid solid. Every upper
floor is cut by two overlapping rectangles that equal the six-corner swept outline plus the 50 mm
margin; the floor slab above the newel square and beside the flights is kept.

The derived operation count is `2·floors + 4·(floors − 1) + 1 + (2·risers − 1)·(floors − 1)`. The
maximum (three floors, 30 risers) is 133 operations, below the shared 256 ceiling; the first
rejected riser total is 31. The complete OperationPlan is built and validated while the request is
validated, so an impossible plan is a 422 before a project or job exists, and again in the worker.

`PlanStair` gains `winders` (three polygons, climbing order) and `newel`; `run_mm` stays the flight
run because winder going varies across a tread. The shared `stairPlanLines` helper draws the two
inner winder risers and a six-point walking line, and the plan editor outlines the newel. Web and
mobile use one shared `checkWinderStair` contract helper for immediate feedback.

Not modelled for this shape: railings (a straight or bent rail would misrepresent the winding
edge, so `railing: true` is rejected), a newel post, stringers, headroom, structure, or any
building-code check. The walking-line rule is a comfort bound, not code compliance.

## Symmetric upper-floor setback follow-up

Rectangle houses with two or three floors may declare one `upper_floor_setback_mm` from 0 to
10,000 mm. Zero preserves the historical plan byte-for-byte. A positive value symmetrically
insets every level above the ground floor and the flat roof on X and Y. The remaining upper
rectangle must be at least 2,000 × 2,000 mm; L/T shapes and one-floor houses fail closed instead
of silently ignoring the field.

Exact shells are created at the inset world-space origin, and each stored 2D floor plan uses the
same measured outline, so floor tabs no longer pretend that a setback level repeats the ground
footprint. If a stair is present, its trusted opening must retain the 350 mm clearance inside the
smaller upper rectangle before the job is accepted and again when the worker restores the request.
This is geometric vertical alignment, not a claim that partitions, columns, wet stacks or load
paths have been structurally engineered.

## Geometric cross-floor review follow-up

The authenticated read-only
`GET /projects/{project_id}/floor-plans/cross-floor-alignment` endpoint compares adjacent saved
levels of the current immutable head. It does not mutate or regenerate either plan.

For internal partition centre-lines it reports one-to-one collinear overlap using a fixed 50 mm
coordinate tolerance and a minimum 1,000 mm shared segment. Exterior walls are removed from this
comparison by the saved footprint boundary. The result exposes counts for both levels and the
total matched length instead of turning a partial match into a binary structural pass.

For typed plans it treats only `bathroom` and `kitchen_living` room outlines as wet zones and
reports one-to-one rectangular overlap of at least 1 m². A plan containing untyped rooms returns
`not_typed`; names are never parsed to guess a bathroom or kitchen. This is footprint overlap only:
fixtures, pipe points, risers and routes do not exist in the current plan contract.

The web plan screen refreshes this report after a coordinated all-floor layout and shows every
adjacent floor pair. It explicitly labels the result as saved 2D geometry, not engineering of
bearing walls, beams, loads, plumbing stacks, pipe routes or code compliance.

## Explicit limits

This is not a general staircase or building-information model. It does not claim:

- spiral stairs, half-turn or other winder counts, winder railings or newel posts, or L stairs with
  unequal landing size;
- independently configured flights per transition;
- stairs inside L- or T-shaped footprints, asymmetric/per-level setbacks or shape changes;
- pitched roofs in this multi-floor scene path;
- one atomic all-floor transaction (web coordinates separate immutable per-floor steps);
- automatic structural optimization of partitions, columns, wet stacks or load paths; the
  geometric report is advisory evidence only;
- facade rebuilding of the multi-body scene (the existing facade endpoint rejects this lineage
  fail closed instead of silently replacing it with its historical single shell);
- structural-code compliance (the 550–700 mm stride is a comfort rule, not a code check), stringers, headroom proof or baluster detailing;
- physical browser/device visual acceptance.

These limits are surfaced in the creator and plan UI rather than being inferred from missing
controls.
