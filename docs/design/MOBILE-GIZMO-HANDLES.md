# Mobile on-model gizmo handles (design)

Status: move-handle increment implemented in `apps/mobile/src/ModelViewer.tsx`; physical-device
touch acceptance remains outstanding. Closes the move-specific item flagged inside row 08 of
`docs/COMPETITOR_UI_ANALYSIS.md`'s 01–20 table ("До полного набора референса остаются
on-model gizmo handles (отложено — нужен отдельный design pass: hit-testing
gizmo-геометрии в raw THREE/expo-gl цикле, screen-space размер handle и axis-constrained
drag без конфликта с orbit/pan/box/lasso режимами)"). Builds directly on
`docs/design/MOBILE-CAD-PANELS-increment1.md`'s established vocabulary — gesture-first
with a numeric escape hatch, flat non-nested controls, a viewport that is never
permanently reduced for a docked panel — and on the mesh-edit/selection machinery that
vocabulary shipped on top of (`0df7dfc`, `952c50b`).

## 0. What this is, and what it deliberately is not

This is **not** a new interaction mode next to orbit/outline/paint/edit, and it does not
add a mode toggle. It is a second, more precise way to grab the *same* `activeEditOperation`
/ `editMagnitude` state `apps/mobile/src/ModelViewer.tsx` already drives today (the
drag-to-scrub rig at `ModelViewer.tsx:1027-1152`). Today a one-finger drag that starts on
the selected component scrubs a single scalar, mapped from vertical screen translation
(`ModelViewer.tsx:1097-1109`). The gizmo adds on-model handles the user can grab instead
of the bare surface, each constrained to one axis or plane, so the drag maps to a
specific direction in model space instead of an undifferentiated scalar.

**Concrete capability gap this closes, not just a UX nicety.** Mobile's `move` operation
today is submitted as `{ op: "move", selection, along_normal_mm: editMagnitude }`
(`apps/mobile/app/project/[id].tsx:1093`) — always along the face normal, a single scalar.
`MeshEditOperation`'s `move` variant also accepts `delta_mm?: Vec3`
(`packages/contracts/src/mesh-edit.ts:19`), an arbitrary 3-vector, but nothing in mobile's
UI can produce one: there is no gesture today that lets a person nudge a selected vertex
sideways in X or Y, only toward/away from the surface it sat on. A three-axis move gizmo
is the first mobile surface that can populate `delta_mm`, not a cosmetic alternative to
an input that already works.

## 1. What's already claimed (read from the current implementation)

Read directly from `apps/mobile/src/ModelViewer.tsx` before designing anything on top:

- **Gesture composition** (`ModelViewer.tsx:1195`): `Gesture.Simultaneous(Gesture.Race(tap,
  longPress, pan), pinch)`. Exactly one of tap/longPress/pan wins the race per touch
  sequence; pinch always runs alongside whichever wins. Any new gizmo-grab behaviour has
  to live inside `pan`'s `onStart`/`onUpdate`/`onEnd` — there is no separate gesture slot
  to add.
- **One-finger pan priority chain today**, in the order `pan.onStart`/`onUpdate` actually
  check it (`ModelViewer.tsx:1029-1121`):
  1. `drawing` (outline/paint mode) — claims the drag as a surface path.
  2. `editing && boxSelect` — claims the drag as a selection rectangle.
  3. `editing && lassoSelect && !boxSelect` — claims the drag as a freehand polygon.
  4. `editing && activeEditOperation && componentSelection.size > 0`: raycasts
     (`hitAt`, `ModelViewer.tsx:716-737`) at the *start* point only, runs
     `componentAtHit` to identify which component was touched, and sets
     `scrubAllowed.current = picked != null && componentSelection.has(picked)`
     (`ModelViewer.tsx:1060`) — i.e. the drag only scrubs the magnitude if it **started
     on a component that is already selected**. This is the existing precedent for "a
     touch must land on something specific to win over orbit," and the gizmo reuses the
     same shape of check, just against different geometry.
  5. Anything else with one pointer → orbit (`ModelViewer.tsx:1115-1120`); two pointers,
     or `viewMode === "2d"` → pan.
- **Hit-testing today is mesh-only.** `hitAt` (`ModelViewer.tsx:716`) raycasts against
  `current.mesh` (or all loaded meshes when `allObjects` is passed for scene-node
  selection) — never against anything else in the scene. Any gizmo handle that extends
  into empty space past the mesh's own silhouette (an arrow tip floating off the surface)
  is **not** hittable by `hitAt` as it exists; gizmo hit-testing needs its own raycast
  target, covered in §3.
- **Overlay rendering pattern.** Selection highlight, symmetry planes, and topology
  wireframe are each a plain `THREE.Group` added straight to `scene` in `onContextCreate`
  (`ModelViewer.tsx:1230-1237`: `markers`, `topologyOverlay`, `symmetryPlanes`,
  `planSelection`), rebuilt by a `useEffect` that calls `clearGroup` then re-adds fresh
  geometry whenever the relevant state changes (e.g. `ModelViewer.tsx:611-642` for
  `symmetryPlanes`, keyed on `[grid, sceneReady, size, symmetryOn]`). The render loop
  itself (`ModelViewer.tsx:1258-1264`) is a bare `requestAnimationFrame` calling
  `renderer.render` — no per-frame app hook exists today. A gizmo that must rescale every
  frame (not just when selection changes) is new to this file and is specified in §2.
- **Axis colour convention already exists and should be reused, not invented.**
  `colors.symmetryX/Y/Z` = `#ff5d6c`/`#52d273`/`#5b9cff` (`apps/mobile/src/theme.ts:27-29`),
  already the X/Y/Z convention for symmetry planes. `colors.selection` = `#ff8a42`
  (`theme.ts:24`) is the "this is picked" colour used for selected topology components.
- **The selection's model-space points are already computed, not something the gizmo
  needs to derive from scratch.** Every path that changes `componentSelection`
  (`pickComponent`, `commitBoxSelection`, `commitLassoSelection`, all in
  `ModelViewer.tsx`) already calls `selectionToPoints(topology, componentKind, next)`
  (`packages/contracts/src/mesh-edit.ts:90`) and hands the result out via
  `onComponentSelection` as `MobileComponentSelection.selection.points_mm: Vec3[]`
  (`ModelViewer.tsx:70-76`). The gizmo's origin is the centroid of that same array —
  no new topology query, just an average over points mobile already has in hand inside
  the component that owns `componentSelection`.

## 2. Gizmo rendering: construction, placement, screen-space-constant size

**Construction — increment 1 ships move only (justified in §6):** three arrow handles
(thin cylinder shaft + cone tip, matching three.js's own `ArrowHelper` proportions so the
look is a familiar CAD-tool shape), one per local axis, coloured `symmetryX`/`symmetryY`/
`symmetryZ`. Each visible arrow is paired with an invisible, fatter "pick proxy" — a
wider-radius cylinder covering the same shaft+tip extent, `visible: false` but still
raycastable (three.js raycasts invisible objects unless `raycast` is nulled, so this just
means not adding it to anything that calls `.render()` differently — it is added to the
scene like any mesh, with a `MeshBasicMaterial` and `visible = false`, or more precisely
excluded from rendering by never being added to a renderable list other than the gizmo's
own hit-test array). The pick proxy exists because a visually thin shaft (the right look)
is too small a target to reliably land a fingertip on; three.js's own `TransformControls`
and Blender's gizmo both use a fattened invisible hit volume for exactly this reason.

**Scene membership.** Add one new `gizmo: THREE.Group` to the `Scene` interface
(alongside `topologyOverlay`/`symmetryPlanes`), created once in `onContextCreate` and
added to `scene` there, mirroring the existing groups exactly. Its three arrow meshes
(and three pick-proxy meshes) are built once, not rebuilt per selection change — rebuilding
geometry on every selection change (as `topologyOverlay` does, because its geometry
*content* changes) is unnecessary here since the arrows are always the same unit shape;
only `gizmo.position` and `gizmo.scale` change.

**Placement.** A `useEffect` keyed on `[componentSelection, activeEditOperation, editing,
boxSelect, lassoSelect]` sets `gizmo.visible = editing && activeEditOperation === "move" &&
!boxSelect && !lassoSelect && componentSelection.size > 0` and, when visible, sets
`gizmo.position` to the centroid of the current selection's `points_mm` (averaged, then
`.sub(current.offset)` the same way every other scene object converts model mm to the
centred scene space — see `markers`' `mesh.position.set(...marker.point).sub(current.offset)`
at `ModelViewer.tsx:707` for the existing precedent). `gizmo.quaternion` is left at the
identity — increment 1's arrows point along the **world** X/Y/Z axes, not a local frame
relative to the selected face, which keeps the one case that matters (lateral nudge in a
fixed, predictable direction) simple; a face-normal-relative gizmo orientation is a refinement,
not a blocker, and is listed in open questions.

**Screen-space-constant sizing — the actual math.** Perspective-camera apparent size of an
object of fixed world-space size shrinks as `1 / distance`. To keep the *rendered* pixel
size constant, the arrow's world-space length must grow proportionally to distance from
the camera:

```
scale = distanceToCamera(gizmo.position, camera.position) * PIXELS_TO_WORLD_AT_UNIT_DISTANCE
```

where `PIXELS_TO_WORLD_AT_UNIT_DISTANCE` is a constant chosen once from the camera's
vertical FOV and the viewport's pixel height, following the standard three.js gizmo
derivation: `worldSizeAtDistance(d) = 2 * d * tan(fov/2) * (desiredPixelSize / viewportPixelHeight)`.
Concretely, pick a target handle length of ~64 screen pixels (comfortably inside a thumb's
reach without dominating a phone-width viewport) and recompute `scale` from that formula
every time distance changes — which, since orbit/pan/pinch can change every frame during a
gesture, means recomputing it **inside the `draw()` render loop** (`ModelViewer.tsx:1258`),
not only inside the placement `useEffect`. This is the one change to the render loop this
design needs: after `requestAnimationFrame(draw)` and before `renderer.render(...)`, if
`current.gizmo.visible`, set `current.gizmo.scale.setScalar(...)` from the formula above
using `current.camera.position.distanceTo(current.gizmo.position)`. This is a single
distance calculation and a `setScalar` call per frame — negligible next to
`renderer.render` itself, and exactly the kind of per-frame bookkeeping three.js's own
`TransformControls` does internally.

**Orthographic (2D plan view) is out of scope for increment 1.** `viewMode === "2d"` is
the floor-plan top-orthographic view (`ModelViewer.tsx:321-336`), not a view mesh-edit
operations are performed in today — `edit` mode's drag-to-scrub, box-select, and lasso
all already assume the 3D perspective camera. The gizmo inherits that same assumption and
is simply not shown when `viewMode === "2d"` (`gizmo.visible` also requires
`viewMode === "3d"`); the orthographic sizing formula (`scale` driven by
`orthographicCamera`'s half-height / viewport pixels rather than distance) is a two-line
addition if mesh-edit ever moves into the 2D view, but nothing today asks for that.

## 3. Hit-testing: gizmo vs. orbit vs. box/lasso select

**New raycast target, separate from `hitAt`.** Add a small helper,
`hitGizmoHandle(x, y): "x" | "y" | "z" | null`, that builds NDC coordinates the same way
`hitAt` does (`ModelViewer.tsx:719-724`) but raycasts only against the three pick-proxy
meshes (`raycaster.intersectObjects(pickProxies, false)`), returning the axis of the
closest hit or `null`. This is intentionally a separate function from `hitAt`, not a mode
flag added to it — `hitAt`'s contract (mesh surface point + normal + face index) has
nothing to do with "which gizmo arm did this touch land on," and conflating them would
make both harder to read.

**Where it slots into the existing priority chain, in `pan.onStart`**
(`ModelViewer.tsx:1029-1062`): run `hitGizmoHandle` **after** the `boxSelect`/`lassoSelect`
branches (those are explicit, user-toggled exclusive modes — if a person turned on
box-select, every one-finger drag is a selection rectangle, full stop, exactly as today)
but **before** the existing "did this drag start on an already-selected surface component"
check. Concretely:

```
scrubAllowed.current = false;
grabbedAxis.current = null;
if (editing && !boxSelect && !lassoSelect && activeEditOperation === "move"
    && componentSelection.size > 0 && event.numberOfPointers === 1) {
  grabbedAxis.current = hitGizmoHandle(event.x, event.y);
  if (grabbedAxis.current) {
    axisDragStart.current = computeAxisProjection(grabbedAxis.current); // §4
  } else {
    // existing surface-pick fallback, unchanged, ModelViewer.tsx:1052-1061
    const hit = hitAt(event.x, event.y);
    const picked = hit && topology ? componentAtHit(...) : null;
    scrubAllowed.current = picked != null && componentSelection.has(picked);
    scrubStart.current = editMagnitude;
  }
}
```

**Why this doesn't falsely capture orbit touches elsewhere on screen.** The pick-proxy
geometry is small and positioned exactly at the gizmo's screen-space location; a touch
anywhere else returns no intersection from `intersectObjects(pickProxies)`, so
`grabbedAxis.current` stays `null` and the existing fallback chain (surface-pick, then
orbit) runs completely unmodified. There is no screen-space-radius heuristic standing in
for real geometry — the pick proxies' own screen-space-constant scale (§2) already keeps
the touch target at a consistent, thumb-sized pixel footprint regardless of zoom, so the
raycast-against-geometry approach is both correct and already touch-friendly without a
second fudge factor.

**Why the gizmo wins over orbit when touched directly.** Exactly because the check runs
inside `pan.onStart` before the code falls through to the orbit-rotation branch at the
bottom of `onUpdate` (`ModelViewer.tsx:1115-1120`) — this mirrors how `scrubAllowed`
already pre-empts orbit today; the gizmo check is a second, more specific pre-emption
inserted at the same point, not a new mechanism.

## 4. Axis-constrained drag: 2D screen delta → 1D model-space distance

Once `grabbedAxis.current` is set (say `"x"`), the drag must map 2D screen pixels to a
signed distance along world X in model millimetres — not reuse the existing flat
"vertical translation only" formula (`ModelViewer.tsx:1100`), since the whole point of a
3-axis gizmo is that each axis has its own screen-space direction depending on camera
orientation.

**Calibration, done once in `onStart` when the axis is grabbed:**

1. Project the gizmo's world position and a point one axis-unit away
   (`gizmo.position + axisUnitVector_mm`) through the current camera to get two screen-space
   points: `origin2D = projectToScreen(gizmo.position)`, `tip2D =
   projectToScreen(gizmo.position + axisUnit)` (`projectToScreen` = the same
   `.project(camera)` + NDC→pixel conversion `commitBoxSelection` already does at
   `ModelViewer.tsx:863-865`, extracted as a shared helper rather than duplicated a third
   time).
2. `axisScreenDir = normalize(tip2D - origin2D)` — the 2D direction, in pixels, that
   moving +1mm along this axis corresponds to **from the camera's current angle**. This is
   the actual fix for the thing a flat vertical-drag mapping cannot express: if the camera
   is angled so the X axis runs mostly left-right on screen, dragging up/down should do
   almost nothing; the existing scrub has no way to represent that, because it always reads
   `event.translationY` regardless of camera angle.
3. `pixelsPerMm = length(tip2D - origin2D)` (from the same two projected points) — this
   is the actual current zoom-dependent scale, replacing the fixed `modelSpan / 300`
   heuristic (`ModelViewer.tsx:1100`) with a value derived from the real current camera
   state, so the drag feels equally sensitive near and far from the camera.

**Per-frame, in `onUpdate`:** project the raw 2D drag delta onto the calibrated axis
direction via a dot product — `scalarPixels = event.translationX * axisScreenDir.x +
event.translationY * axisScreenDir.y` — then `deltaMm = scalarPixels / pixelsPerMm`. Add
this to the magnitude the drag started at (mirroring `scrubStart.current` today), run it
through `snapPoint` exactly as the existing scrub does when `grid.snap` is on
(`ModelViewer.tsx:1107`), and report it through `onEditMagnitudeChange` — **but** since a
3-axis gizmo now needs to report which axis moved, not just a scalar, the natural
contract change is for the `move` operation specifically to carry `delta_mm: Vec3` (already
legal per `MeshEditOperation`, §0) with the two non-grabbed axes left at their last
committed value (0 unless a previous gizmo drag on a different axis already changed them
in the same editing session). This is a product/contract decision for whoever reviews
this design, flagged explicitly in open question 1, not assumed silently — it is the one
place this design brushes against `apps/mobile/app/project/[id].tsx`'s `runMeshEdit`
(`project/[id].tsx:1073`) rather than staying purely inside `ModelViewer.tsx`.

**Why a dot product against a calibrated screen-space axis direction, and not something
fancier (e.g. unprojecting a 3D ray and intersecting it with a 3D line through the axis).**
Both are mathematically close for a single straight-line constraint, but the screen-space
projection approach needs no new linear-algebra machinery beyond what `commitBoxSelection`
already does (project a 3D point to 2D), stays numerically well-behaved when the axis is
nearly perpendicular to the view (the 3D ray/line intersection approach degenerates badly
exactly there, dividing by a near-zero determinant), and is the same technique three.js's
own gizmo-dragging reference implementations use for linear handles. For rotate (deferred
to increment 2, §6) the correct analogous technique is different — angle-around-a-projected-
center, not axis projection — which is itself a reason rotate doesn't belong in the same
increment as move.

## 5. Coexistence with drag-to-scrub and the numeric escape hatch

**Not a toggle. Always on when it's unambiguous to be on.** The gizmo is visible exactly
when `editing && activeEditOperation === "move" && componentSelection.size > 0 &&
!boxSelect && !lassoSelect` (§2) — the same conditions under which drag-to-scrub is
already active today, so nothing new has to be decided or remembered by the person using
it. This is a direct application of the increment-1 doc's own framing ("gesture-first,
numeric as an escape hatch, not the other way round," `MOBILE-CAD-PANELS-increment1.md:165`)
one level further: the gizmo doesn't replace the existing scrub-on-surface drag or the
bottom sheet's live mm chip / numeric `TextInput` escape hatch (`MOBILE-CAD-PANELS-
increment1.md:187-191`) — it is a **third**, more targeted entry point into the same
`editMagnitude` state, alongside "drag directly on the selected surface" (unchanged,
stays as the fallback when a touch misses every gizmo handle, §3) and "tap the chip, type
an exact number" (unchanged). A person who never notices the arrows loses nothing; a
person who grabs one gets axis-precise control the flat scrub cannot offer at all (§0).
An explicit mode toggle would violate the brief's "never hide capability" framing by
making the more capable interaction something a person has to discover a switch for
first — the whole lesson increment 1 already drew from Nomad Sculpt's flat, undocked
tool-access pattern.

**Thin-sheet rule carries over unchanged.** The gizmo renders in the 3D viewport, which
`MOBILE-CAD-PANELS-increment1.md`'s thin bottom sheet already leaves fully visible and
interactive underneath it (`MOBILE-CAD-PANELS-increment1.md:177-178`) — no change to
`EditModeSheet.tsx`'s layout is implied; the sheet still shows operation name, live mm
chip, Apply/Cancel, and the chip's tap-to-type escape hatch, exactly as already designed.

## 6. Scope boundary for increment 1

**Ships: move only**, for three concrete reasons, not just "it's the easiest":

1. **It is the only operation with a real capability gap today** (§0) — mobile's `move`
   cannot go sideways at all without this; `extrude`/`inset`/`bevel_edges` are already
   fully expressible as the single scalar they already are (extrude/inset distance along
   normal, bevel width), so a gizmo adds precision/feel to them but not a new degree of
   freedom the way it does for move.
2. **Its hit-testing and drag math are the simplest of the three gizmo kinds**, and this
   design pass's own instructions call that out directly: linear axis handles need one
   raycast against a small set of proxy meshes and one dot-product projection (§3–§4).
   Rotate needs angle-around-a-projected-center math and ring geometry whose "front" vs.
   "back" half (relative to the camera) usually needs different render/pick treatment so
   a person doesn't grab the far side of a ring they can't see straight-on. Scale needs a
   decision this design shouldn't make silently — per-axis boxes (3 more handles, now 6
   total with move's arrows if both exist) vs. one uniform-scale handle — and mobile
   already has a *working* uniform bounded-scale control via the existing vertical-drag
   scrub (`activeEditOperation === "scale"` branch, `ModelViewer.tsx:1102`), so the
   incremental value of a scale gizmo is smaller than move's.
3. **Shipping one gizmo kind end-to-end and getting real device feedback on it (§8) before
   building two more** is the same incremental-proof posture `MOBILE-CAD-PANELS-increment1.md`
   itself argues for throughout (e.g. its open question 2 proposing grid/snap/symmetry ship
   standalone first) — three new hit-testing/drag-math shapes landing and being judged on a
   phone screen at once is a worse way to find out the pixel-target size or the axis-colour
   contrast is wrong than one.

**Deferred to increment 2:** rotate (ring handles, angle-around-projected-center drag,
front/back ring half handling), scale (per-axis vs. uniform decision above), and the
`delta_mm` three-axis accumulation question in §4's open question 1 if it's decided the
contract should change rather than keep submitting one axis at a time as three separate
`move` operations in the same editing session.

## 7. Touch list

| File | Change |
|---|---|
| `apps/mobile/src/ModelViewer.tsx` | Add `gizmo: THREE.Group` (three arrow meshes + three invisible pick-proxy meshes, built once) to the `Scene` interface and `onContextCreate`; add the placement `useEffect` (§2) keyed on selection/mode/operation state; add the per-frame screen-space-constant scale update inside `draw()` (§2); add `hitGizmoHandle` (§3) alongside the existing `hitAt`; add `grabbedAxis` ref and the calibration step (`axisScreenDir`, `pixelsPerMm`) in `pan.onStart`/`onUpdate` (§3–§4), gated the same way the existing `scrubAllowed` branch is gated; extract the NDC→pixel screen-projection helper already duplicated inline in `commitBoxSelection`/`commitLassoSelection` (`ModelViewer.tsx:863-865`, `~950`) so the gizmo calibration step can reuse it instead of a third copy |
| `apps/mobile/src/theme.ts` | No new colour tokens needed — reuses `colors.symmetryX/Y/Z` and `colors.selection` as-is (§2) |
| `apps/mobile/app/project/[id].tsx` | Only touched if open question 1 (§4) resolves toward changing `runMeshEdit`'s `move` branch (`project/[id].tsx:1093`) from `along_normal_mm` to `delta_mm`; no other change implied by this design |

No change to `packages/contracts` is required for move-along-world-axis, since
`delta_mm?: Vec3` already exists on the `move` operation (§0) — only mobile's own
`runMeshEdit` call site would need to populate it differently, which is why that single
line is the only cross-file touch point this design has outside `ModelViewer.tsx`.

## 8. Proof plan

**What typecheck/build can verify.** `apps/mobile`'s `typecheck` script
(`tsc -p tsconfig.json --noEmit`, same one `MOBILE-CAD-PANELS-increment1.md`'s proof plan
already describes as the only check this package has — there is still no test runner
configured) catches: wrong argument shapes into `selectionToPoints`/`MeshEditOperation`;
a `grabbedAxis` type that doesn't line up with the three axis literals; the projection
helper's signature being used consistently across `commitBoxSelection`,
`commitLassoSelection`, and the new calibration step. It proves the gizmo code *compiles
against the same contracts the rest of the file already uses correctly* — it does not,
and cannot, prove any of the following.

**What genuinely needs a physical device, stated honestly, same standard as every other
mobile design doc in this repo:**

1. **Does the pick-proxy touch target feel right at a real fingertip, at real screen
   DPI?** The ~64px handle-length target in §2 is a starting number, not a verified one;
   like `MOBILE-CAD-PANELS-increment1.md`'s own open question 5 on overlay budgets, this
   needs on-device judgment, not a simulator window.
2. **Does grabbing an arm actually feel axis-constrained, or does the screen-space
   projection in §4 feel "off" at steep camera angles** (e.g. looking almost straight down
   the X axis, where `axisScreenDir` is nearly zero-length and the drag should feel
   "stuck" rather than erratic)? This is exactly the kind of degenerate case that is easy
   to reason about on paper (§4 names it) but only a thumb on a screen can confirm feels
   acceptable rather than broken.
3. **Does the gizmo visually read against the model at typical phone brightness/contrast**,
   especially where an arrow of one axis colour sits close to a similarly-coloured part of
   the model, or where two arrows nearly overlap head-on from the current camera angle?
4. **Does the per-frame `draw()` scale update (§2) hold frame rate** on a mid-range phone
   GPU — this is the same open, device-dependent question `MOBILE-CAD-PANELS-increment1.md`'s
   open question 5 already flags for the topology overlay budgets, now with one more
   per-frame computation added to the same render loop; nothing on paper answers this.
5. **Does the fallback to surface-drag scrub (when a touch misses every gizmo handle)
   still feel reachable**, or does the gizmo visually crowd out the "just drag the
   selected face" gesture it used to be able to use anywhere on that face?

**Manual verification plan once built:** on at least one phone-class device (per
`MOBILE-CAD-PANELS-increment1.md`'s own precedent, not just a simulator), select a face,
choose Move, confirm three coloured arrows appear at the selection centroid; drag each arm
in turn and confirm the live mm chip changes only that axis's value while the model
visibly moves along the expected world direction; rotate the camera to a steep angle along
one axis and confirm that axis's arm becomes hard to read directionally but does not crash
or silently do nothing permanently; zoom in and out and confirm the arrows stay a roughly
constant size on screen rather than shrinking to invisible or ballooning over the model;
drag on the bare selected surface away from any arrow and confirm the existing scrub
fallback still works unchanged. None of this is claimed done until it is actually run on a
device.

## 9. Open questions for the owner

1. **Does a grabbed axis submit `delta_mm: Vec3` (accumulating per-axis across a single
   editing session before Apply) or does each axis-drag become its own immediately-applied
   `move` operation with `along_normal_mm` still used only when no gizmo was involved?**
   §4 flags this as the one place this design touches `runMeshEdit` outside
   `ModelViewer.tsx`; it's a product call about whether "drag X then drag Y then Apply
   once" should compose into one operation or several, not something this design should
   decide unilaterally.
2. **Should the gizmo's arrows orient to the selected face's local normal frame instead of
   always pointing along world X/Y/Z**, once rotate (increment 2) exists and a local frame
   becomes meaningful for more than just move? §2 deliberately keeps world-axis orientation
   for increment 1 to avoid needing a frame-construction decision (which face's normal wins
   when a multi-face selection has several) before it's load-bearing.
3. **Is a 64px target handle length the right starting point for phone screens, or should
   it differ between phone and the tablet layout** `MOBILE-CAD-PANELS-increment1.md`'s own
   open question 3 already flags as an unresolved phone-vs-tablet layout question? This
   design inherits that open question rather than re-deciding it.
4. **Should increment 2's rotate ring hide or dim its far (camera-facing-away) half**, the
   way most 3D-authoring tools do to avoid a person grabbing geometry they can't see
   clearly, or is a full ring acceptable for a first rotate pass? Flagged now so it isn't
   quietly decided mid-implementation later.
