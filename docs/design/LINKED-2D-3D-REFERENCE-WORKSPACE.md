# Linked 2D / 3D / reference workspace

Status: product direction accepted from owner references on 2026-10-09. This document
defines the interaction before implementation; it does not replace the existing exact
model, floor-plan, reference-image, annotation, or immutable-version contracts.

## Decision

Build one **linked dual-view workspace**, not several unrelated 2D/3D switches.

The two panes always show two representations of one project and share selection. The
object is not copied between panes and cannot silently diverge. A divider can be resized,
the panes can be swapped, and either pane can be expanded to full screen.

Presets:

1. **Plan ↔ Model** — a real versioned 2D floor plan or orthographic drawing on the left,
   the current 3D version on the right.
2. **Reference ↔ Model** — a calibrated photo/drawing/site image on the left, the current
   3D version on the right.
3. **Source ↔ Current** — imported/previous immutable model version on the left, the working
   version on the right. Applying a source choice creates a new version; it never overwrites
   either side.

This covers object design and architecture without pretending that a single photograph is
metric 3D data.

## Device layout

### Phone

One large viewport. A compact segmented control switches `Фото / 2D / 3D`; selection and
camera target survive the switch. A swipe on the viewport may move to the adjacent mode,
but all actions remain available as labelled controls.

### Tablet and desktop

Two resizable panes plus one inspector. Default orientation is source/reference/plan on the
left and current 3D result on the right. The centre divider contains:

- linked-selection toggle;
- swap panes;
- expand left/right;
- for model versions only, an explicit `Use as current` action with version creation.

The inspector stays on the outer edge; it does not cover either viewport.

## Linked interactions

- Tap a room, wall, component, annotation, or scene node in either pane: highlight the same
  entity in the other pane and frame it there.
- A 2D edit updates the shared exact plan/feature data and rebuilds the 3D child version.
- A 3D selection exposes its plan footprint when one exists; unsupported free-form geometry
  says so rather than inventing a footprint.
- Reference images use calibrated points, scale, and 2D↔3D anchors. Moving an anchor is
  reversible and never deforms the model implicitly.
- Optional camera sync links only target/selection by default. Full pan/zoom/orbit sync is a
  separate toggle because perspective and orthographic views do not share the same camera.

## Architecture/site mode

The left pane may show a yard/facade photo, floor plan, or site image; the right pane shows
the building/landscape model. The first increment supports calibrated points and linked
annotations. Perspective matching, occlusion, AR placement, multi-photo registration, and
true site georeferencing are later bounded increments.

A single uncalibrated yard photo is visual reference only. It must not be presented as a
measured placement or used to derive dimensions without an explicit known distance.

## Existing foundations to reuse

- versioned project floor plan and auto-layout client APIs;
- the mobile/web 3D viewers and scene-node selection;
- project reference-image upload, calibration, and measurements;
- versioned plan annotations with photo attachments and 2D↔3D model anchors;
- immutable project versions and source/current provenance.

The missing work is a shared workspace/view-state contract, mobile 2D rendering, linked
entity selection, and the adaptive phone/tablet shell — not a second model store.

## Delivery order

1. **Plan ↔ Model MVP:** tablet/web split, phone `2D/3D` switch, linked room/wall/node
   selection, resizable divider, expand/swap.
2. **Reference ↔ Model:** calibrated photo/drawing, anchor creation and linked navigation.
3. **Source ↔ Current:** immutable before/after version comparison and explicit promotion.
4. **Architecture/site extensions:** perspective match, multi-photo registration, AR/site
   placement after the calibrated-reference flow is hardware-tested.

## MVP acceptance

- Opening a project with a floor plan shows the same selected wall/room in 2D and 3D.
- Editing a supported plan entity creates a new model version; undo is version navigation.
- Phone switching preserves the selected entity and camera target.
- Tablet rotation preserves pane sizes within bounded defaults.
- Reference photos remain source assets with calibration/anchor provenance.
- Unsupported geometry and uncalibrated photos fail honestly; no guessed correspondence or
  silent copy is created.
