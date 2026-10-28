# Synchronized print-farm queue

The print-farm planner still produces a non-dispatching `BatchPlanOut` with
`dispatch_ready=false`. A workspace may now retain one shared snapshot of that plan through
`GET/PUT/DELETE /api/v1/print-farm/queue`.

Safety and concurrency boundaries:

- viewers may read; editors and owners may save or clear;
- updates and deletion use compare-and-swap `base_revision`, so an older phone cannot silently
  overwrite a newer desktop change;
- the server re-resolves every immutable version, project, printer profile, bed and material;
  cross-workspace, renamed/forged, duplicated or out-of-bed placements fail closed;
- the response remains a plan only: saving never creates G-code, reserves a printer or sends a
  controller command;
- mobile keeps a validated AsyncStorage cache for offline display, but the server revision is the
  canonical multi-device copy.

This closes the single-device persistence gap in reference 93. Dispatch, live job completion,
failure recovery and physical multi-printer acceptance remain separate work.
