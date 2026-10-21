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

Rows `52–100` remain **not audited** in this file until their current code paths are inspected. Existing
entries in `docs/IMPLEMENTED.md` and `docs/IN_PROGRESS.md` remain evidence to reconcile, not automatic
proof that a visually similar retained reference is complete.
