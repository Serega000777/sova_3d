# Handoff — 2026-09-28 (Codex)

Continue from `docs/TZ_GAP_AUDIT_2026-09-21.md`; it remains the detailed source of truth.

After the 26 September handoff:

- T-224 follows the wrapped Shap-E model and releases the unused CLIP tower after computing
  conditioning (measured 1159.5 MiB on the real checkpoint).
- T-225 gives Shap-E jobs a 70-minute budget.
- T-226 adds explicit 16-step fast and 32-step detailed generation profiles in web/mobile
  and records the selected profile in provenance.
- T-227 adds bounded 2-opt after the slicer's nearest-neighbour route; its regression route
  cuts travel by 27%.
- T-228 restores deterministic formatting/contracts; GitHub Actions run 36334370623 passed.
- T-229 connects generated G-code to a server-side OctoPrint bridge. The slicer can upload,
  select, and optionally start a print. Local `stub` mode tests the complete flow without a
  printer; production refuses the stub. Credentials never enter the browser.
- T-230 reads normalized live job/printer state (progress, time and temperatures) and proxies
  a bounded camera snapshot. The slicer polls after dispatch and can refresh the camera; stub
  mode provides an explicitly labelled hardware-free preview.

Major remaining items are multi-room RoomPlan on Apple hardware, Alembic/binary X3D, tree
supports, normal/AO maps, and merge semantics for simultaneous version edits.
