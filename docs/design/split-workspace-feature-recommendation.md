# Split workspace ("reference ↔ model" pane) — product recommendation

Context: owner saw a 2D/3D toggle in a reference Studio UI mockup and asked whether SOVA
should add a split workspace — either (a) a generic idea/reference pane next to the
work-in-progress model, or (b) a yard/building photo pane that gets click-copied into a
working view for architecture-style work.

Note up front: this exact direction was already worked through today and accepted as
`docs/design/LINKED-2D-3D-REFERENCE-WORKSPACE.md`. What follows checks that decision
against the four questions rather than proposing a second, competing design.

## 1. What problem is this actually solving?

Not a new problem — SOVA already has two of the three pieces the owner is describing, just
not unified:

- **Reference photo, already shipped**: `apps/web/src/app/projects/[id]/page.tsx` has a full
  `referenceImage` feature (state at line ~404, UI ~2640-2692) — upload a photo, calibrate it
  against a known distance/width, set opacity/offset, and overlay it *into the 3D viewport*
  as a measurement/scale aid. It solves "reference next to model" for scale calibration, but
  the UI treatment is an overlay/underlay inside one view, not a resizable dual pane, and it
  has no equivalent on the 2D plan side.
- **Multi-photo in AI commands, shipped yesterday** (`bf1e74c`): lets a user attach several
  photos to one AI command. This covers "show the AI a reference while asking for a change,"
  which is a different need (input to generation) than "keep a reference visible while I work
  across multiple steps" (persistent comparison view). It doesn't substitute for a dual pane.
- **2D plan annotation, shipped (F-087)**: `PlanEditor`-class markup lets a user pin/annotate
  a floor plan with attached photos and jump pins to the matching 3D point. This covers
  architecture reference-marking at the *point* level, but not a persistent side-by-side
  "photo here, model there" view.

So the real gap is a **persistent, linked, dual-representation view** — plan/photo/prior
version on one side, current 3D on the other, with shared selection — not a brand-new
reference-storage capability. The owner's instinct ("this is a cool feature") is really
pointing at *presentation and linkage*, not data capture.

## 2. Comparing the two framings

- **(a) Generic idea/reference ↔ model pane**: broadly useful (organic generation, mesh
  editing, CAD), but "idea/reference" is vague — a sketch? a competitor screenshot? a prior
  version? Needs a concrete object on the left or it's just a second image viewer.
- **(b) Yard/exterior photo → click-to-copy → architecture pane**: narrower, and partially
  redundant with what's shipped — F-087 plan annotation and the existing reference-image
  overlay already let a user keep a site photo next to geometry. "Click-to-copy" also implies
  duplicating an asset into a workspace, which risks exactly the kind of silent-divergence bug
  SOVA's versioning model is designed to avoid (a copy that quietly drifts from its source).

The accepted direction in `LINKED-2D-3D-REFERENCE-WORKSPACE.md` resolves both: it generalizes
(a) into three concrete, scoped presets — **Plan↔Model**, **Reference↔Model**,
**Source↔Current** — and folds (b) in as the "Reference↔Model" preset applied to a site
photo, explicitly keeping the object as one shared, selection-linked entity rather than a
copy. That's the better third framing the task asked me to consider if (a)/(b) were
insufficient — except it's already written and accepted, so no further option-generation is
needed.

## 3. Recommendation

Endorse the existing design as scoped, with one emphasis: respect the "never permanently
steal viewport space" lesson from `docs/design/MOBILE-CAD-PANELS-increment1.md`. The accepted
doc already does this correctly —

- **Desktop/tablet**: resizable two-pane split with swap/expand, not a fixed 50/50 — same
  spirit as the dismissible/flat panel philosophy, just adapted because two *views* (not
  tool panels) are the actual content being compared.
- **Phone**: no split at all — a segmented `Фото/2D/3D` switch, preserving selection/camera
  across switches. This is the right mobile treatment; a true split pane on a phone-width
  screen would recreate the exact "panels crowd the viewport" problem the tablet-panel doc
  warned about.

This is correctly scoped as **web + tablet primarily, mobile gets a lightweight switch, not
a split**. That matches screen-space reality rather than forcing one layout everywhere.

## 4. Scope/complexity estimate

Mostly **UI/layout and state-linkage work reusing existing machinery** — cheap relative to a
new capability:

- Reference-image upload/calibration, plan annotations, 3D viewers, and immutable versioning
  already exist and are the listed reuse targets in the accepted doc.
- New work is the shared workspace/view-state contract, linked-selection plumbing between
  panes, mobile 2D plan rendering, and the adaptive phone/tablet shell.
- What this is **not**: there's no "trace over this photo to generate 3D" AI capability
  implied or required for the MVP. The doc is explicit that an uncalibrated photo stays
  visual reference only, never a source of inferred dimensions — correctly keeping this out
  of "new AI capability" territory and in "view composition" territory. If the owner later
  wants actual photo-to-3D tracing assistance, that's a distinct, much larger feature and
  should be scoped separately, not bundled into this one.

**Bottom line**: approve and build per the existing `LINKED-2D-3D-REFERENCE-WORKSPACE.md`
delivery order (Plan↔Model MVP → Reference↔Model → Source↔Current → architecture/site
extensions). No new design decision is needed; the owner's idea is already the accepted
plan.
