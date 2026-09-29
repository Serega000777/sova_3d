# Tree supports handoff — 2026-09-29

## Scope and task identity

Implemented the F-054 slicer gap recorded in `docs/TZ_GAP_AUDIT_2026-09-21.md`: tree/organic
supports are now an alternative to the existing grid columns. This was an out-of-list task; there
is no separate T-number in `docs/codex_tasks.json`. The existing F-054 and T-222 grid path remains
the default and was not removed.

## Implementation

- `SliceSettings.support_type` and the slice API accept `"grid"` (default) or `"tree"`.
- The web slicer exposes **Сетка / Дерево** controls when supports are enabled and sends the
  selected type through the generated OpenAPI client contract.
- Tree generation reuses the existing overhang detector and 4 mm contact sampling, including the
  ray-cast choice of the closest supporting surface below each contact (bed or model).
- Contacts with the same supporting height and within a bounded 12 mm XY cell are assigned to a
  shared trunk. Branches descend toward that trunk at at most 50 degrees from vertical. Nearby
  branches therefore merge before the trunk reaches the supporting surface.
- Every proposed branch and extended trunk is ray-tested against the mesh. If the route crosses
  the model or an overhang is too low to reach the trunk at the angle limit, that contact falls
  back to an independent grounded vertical tip instead of silently losing support.
- Each layer interpolates the branch centreline, unions overlapping 1.6 mm branch sections, and
  removes the current model cross-section as keep-out geometry. Tree contacts use small dense
  two-layer tips and retain the existing one-layer Z gap. Grid supports retain their wider dense
  interface cells.
- Slice statistics now report `support_type`, `support_branches`, and `support_trunks`; the legacy
  `support_columns` remains as the number of detected overhang contacts for compatibility.

On the 30 x 30 mm T-overhang regression model, the same complete slice measured 3906.1 mm of
filament with grid supports and 782.3 mm with tree supports (model and supports combined). The
test asserts the invariant rather than these implementation-specific exact values.

## Tests

New worker regressions cover:

- less total extrusion for tree than grid on the same overhang;
- every contact connected through a branch/trunk to the nearest model surface below;
- the 50 degree branch-angle bound;
- a low overhang directly above the bed, which conservatively falls back to grounded tips;
- a very high overhang, which merges multiple contacts into fewer trunks.

API coverage verifies that `support_type="tree"` reaches the queued job/G-code and that unknown
values are rejected with HTTP 422.

Final pytest output:

```text
worker focused: 37 passed in 11.92s
worker full:    268 passed, 11 skipped, 75 warnings in 110.60s (0:01:50)
API printing:    14 passed, 5 warnings in 9.07s
```

The 11 worker skips are existing optional/live or OCCT-dependent tests. Warnings are existing
dependency deprecations (pycollada/NumPy, scikit-image/NumPy). API warnings are existing Starlette,
pytest-return and Alembic configuration warnings.

Static verification:

```text
worker ruff: All checks passed!
worker mypy: Success: no issues found in 64 source files
API ruff:    All checks passed!
API mypy:    Success: no issues found in 195 source files
contracts typecheck: passed
web typecheck:       passed
```

## Deliberate limitations

This is a deterministic basic tree-support implementation, not a production-grade Cura or
PrusaSlicer organic-support planner:

- merging is one level per bounded XY group (tips into one trunk), not recursive global tree
  optimization or load/stress-aware multi-level branching;
- collision tests validate branch centrelines, while per-layer keep-outs clip the full printed
  section; there is no volumetric nozzle/head collision simulation;
- branch/trunk width is fixed rather than increasing with accumulated load or height;
- contacts still come from the existing regular 4 mm overhang sample, not adaptive surface
  sampling, painted blockers/enforcers, or bridge-direction analysis;
- no separate UI controls expose merge radius, branch angle, or tip width yet.

These constraints are explicit so this implementation should not be represented as equivalent to
the mature organic-support algorithms in Cura or PrusaSlicer.
