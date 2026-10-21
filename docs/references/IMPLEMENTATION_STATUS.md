# Sova 3D — implementation status by reference

This file is the implementation companion to `CATALOG.md`. A retained image proves the requested
concept, not implementation. Rows are added here only after the current repository path and its
acceptance boundary have been checked.

Status values:

- **verified** — the complete stated reference capability has meaningful automated or device proof;
- **partial** — a real end-to-end path exists, but a visible or acceptance boundary remains;
- **missing** — no functional path exists;
- **externally blocked** — completion needs unavailable hardware, credentials, provider or legal input;
- **not audited** — the retained reference has not yet been reconciled with current code.

## Extended product scenarios (51–100)

| ID | Status | Implemented boundary | Remaining boundary | Evidence |
| --- | --- | --- | --- | --- |
| 51 | partial | Mobile/tablet «Проверка» launches the existing non-mutating GLB integrity pipeline and reports geometry, material/texture preservation and metric bounds separately. Malformed and failed reports fail closed; absent appearance evidence stays yellow/unknown rather than green. | Physical iPhone/iPad visual acceptance and a dedicated desktop/web presentation are not complete. The check validates conversion integrity; it is not a structural or regulatory certification. | contracts parser tests; mobile source tests/typecheck; worker export tests |
| 53 | partial | Mobile/tablet «Проверка посадки» selects a second workspace project and uses the existing exact two-version fit-test job. Automatic placement checks bounded rotations/faces and returns measured overlap or clearance, advice and the existing explicit immutable-fix path. | The reference's photo/room-style visual envelope overlay, manual mobile placement controls and physical touch acceptance are not complete. | existing API/worker fit tests; mobile source tests/typecheck |
| 55 | partial | Mobile/tablet has a dedicated printer-profile screen reachable from Profile. It loads the workspace's typed printer models, materials and profiles, creates a real profile, marks the first one default, can switch the default, and shows the effective nozzle, material and layer height used by print preparation. | Product photography, direct printer connectivity/status and physical phone/tablet interaction remain unverified. Calibration is tracked separately as reference 56. | existing API profile/authorization tests; mobile 41 source tests/typecheck |
| 56 | partial | Each mobile/tablet printer profile opens a three-stage calibration flow. It builds the real deterministic coupon project, accepts only a succeeded build job, opens that project for ordinary preparation, records any valid subset of seven caliper readings, and shows the server-derived hole, peg, XY, shrinkage and flow corrections separately. The UI explicitly says coupon creation does not start a printer and learned values affect only future preparation. | Slicing/dispatch remain explicit later actions; there is no automatic measurement, independent X/Y correction, or physical phone/printer acceptance. | API calibration 10/10; mobile 45 source tests/typecheck |

Rows `52`, `54`, and `57–100` remain **not audited** in this file until their current code paths are inspected. Existing
entries in `docs/IMPLEMENTED.md` and `docs/IN_PROGRESS.md` remain evidence to reconcile, not automatic
proof that a visually similar retained reference is complete.
