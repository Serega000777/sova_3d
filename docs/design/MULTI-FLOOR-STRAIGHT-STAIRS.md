# Item 26 — bounded multi-floor house and straight stair

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

## Explicit limits

This is not a general staircase or building-information model. It does not claim:

- L-, U-, winder or spiral stairs;
- independently configured flights per transition;
- arbitrary, L- or T-shaped multi-floor footprints;
- pitched roofs in this multi-floor scene path;
- floor-elevation-aware room auto-layout or furniture placement;
- facade rebuilding of the multi-body scene (the existing facade endpoint rejects this lineage
  fail closed instead of silently replacing it with its historical single shell);
- structural-code compliance, landings, stringers or baluster detailing;
- a mobile creator;
- physical browser/device visual acceptance.

These limits are surfaced in the creator and plan UI rather than being inferred from missing
controls.
