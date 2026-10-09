# Mobile CAD/mesh-edit/topology panels — increment 1 (design)

Status: design only, no code. Addresses the confirmed client-parity gap in
`docs/COMPETITOR_UI_ANALYSIS.md:72` ("mobile показывает модель, но полной панели
topology/grid/snap/symmetry и mesh-edit нет") and F-086
(`docs/FEATURE_REGISTRY_ADDENDUM.md:13`), named as the nearest client-side remainder in
`docs/IN_PROGRESS.md:14`. Grounded in `docs/COMPETITOR_BRIEF_HUNYUAN_NOMAD_2026-10-08.md`
Part 2/3 (Nomad Sculpt's UI-architecture lesson) and in what `apps/mobile` and
`packages/contracts` actually contain today, read directly for this design.

## 0. Why this is UI-architecture work, not kernel or contract work

Unlike T-247/T-248, every piece of machinery this feature needs **already exists and is
already platform-agnostic**:

- `packages/contracts/src/topology.ts` holds `buildTopology`, `componentAtHit`,
  `applySelection`, `overlayEdges`, `selectInRect`, and the whole grid/snap/symmetry helper
  set (`defaultGrid`, `suggestGridStep`, `snapPoint`, `symmetricPoints`,
  `GRID_STEPS_MM:topology.ts:1264`) — pure, synchronous TypeScript, zero DOM/web
  dependency, already imported by `apps/web/src/components/ModelViewer.tsx:663`
  (`buildTopology(positions, index, options)` from the loaded geometry's own
  `positions`/`index` arrays — nothing server-side).
- `packages/contracts/src/mesh-edit.ts` holds the `MeshEditOperation` union
  (`move`/`extrude`/`inset`/`delete_faces`/`bevel_edges`/`detail`) and
  `selectionToPoints`, which turns topology ids into the millimetre coordinates the API
  actually accepts — again pure TS.
- `packages/contracts/src/client.ts:709` already exposes `editMesh(versionId, body)` →
  `POST /api/v1/models/{id}/mesh-edit`, and `getMeshModifierStack`/`updateMeshModifierStack`
  (`client.ts:1031-1041`) for the modifier stack. `apps/mobile/app/project/[id].tsx` already
  holds a `client` instance from `useSession()` (`project/[id].tsx:84`) and already calls
  other methods on it (`createEdit`, `paintModel`, `askEngineer`) — `editMesh` is one more
  call on an object mobile already has, not a new integration.
- Mobile's `ModelViewer.tsx` **already does ray-cast picking, gesture-mode switching, and
  stylus detection** for the existing `outline`/`paint` draw modes (`hitAt`,
  `drawStart`/`drawMove`/`drawEnd`, the `Gesture.Pan/Pinch/Tap/LongPress` rig at
  `ModelViewer.tsx:260-421`), and already imports shared contract helpers
  (`dominantAxis`, `pathToRegion`, `planeAxes`, `Surface`, `RegionSelection`) the exact same
  way `buildTopology`/`componentAtHit` would be imported. There is no "does mobile have a
  raycasting/gesture layer" question to answer — it has one, in production, today.

**Conclusion that shapes every section below: this increment adds no new contract types,
no new API endpoint, and no native module.** It is entirely `apps/mobile` UI work that
consumes machinery that already agrees, byte-for-byte, with what the web Studio uses. The
one real gap found during this research (§4) is cosmetic: mobile's `hitAt()` doesn't yet
keep the raycast's `faceIndex`, which `componentAtHit`'s `PickHit.sourceFace` needs.

## 1. Precise scope boundary

F-086 names five capability groups: (a) topology visualization, (b) selection, (c)
versioned direct mesh edits, (d) grid/snap/symmetry, (e) surface-detail parametric
operations (circular/square profiles, ribs/knurling, inset/extrude, bevel,
emboss/deboss with exact dimensions). Desktop (`apps/web`) ships all five through four
components of very different interaction weight:

| Web component | Interaction weight | Why it matters for the cut |
|---|---|---|
| `TopologyOverlay.tsx` | Read-only rendering + box-drag select | Cheap: geometry buffers + one raycaster pass per vertex |
| `MeshModifierStackPanel.tsx` (103 lines) | Toggle + reorder list | Cheap: a flat list, no numeric input at all |
| `MeshEditPanel.tsx` (372 lines) | Numeric fields per op; `detail` op alone carries 9 distinct numeric fields (diameter/width/height/rotation/areaW/areaL/pitch/rib/angle) plus shape/mode/pattern pickers | Expensive: the `detail` sub-panel is a dimensioned-CAD input form, not a toggle |
| `ExactCadPanel.tsx` (651 lines) | Sketch point lists, arc centers, NURBS control points/weights/knot vectors/multiplicities, per-segment constraint toggles | Very expensive: this is a desktop numeric-CAD authoring surface, not adaptable to touch without its own ground-up design |

**In scope for increment 1** — "read and touch the mesh," the same baseline cut the task
brief proposed and that this research confirms is the right line, because everything in
it is either already-shared pure logic or a toggle/chip UI with no numeric-precision
design problem:

- **Topology visualization**: wireframe edges + vertex points overlay, toggleable, ported
  from `TopologyLayer`'s logic (not its react-three-fiber JSX — mobile manages raw THREE
  objects in `ModelViewer.tsx`'s `onContextCreate`/`draw` loop, so this is a direct-THREE
  reimplementation of the same `segmentGeometry`/`pointGeometry`/`faceGeometry` builders,
  which are plain functions over `MeshTopology`, not React components — trivially portable).
- **Selection**: tap-to-pick one vertex/edge/face via `componentAtHit`, a persistent
  "multi-select" toggle chip that switches `applySelection`'s mode between `replace` and
  `toggle` (no box/lasso drag — see the explicit cut below).
- **Direct mesh edits**: `move`, `extrude`, `inset`, `delete_faces`, `bevel_edges` — the
  five non-`detail` members of `MeshEditOperation`. Each submits through the same
  `client.editMesh` call web uses, gets back the same `MeshEditReport`.
- **Grid/snap/symmetry**: step picker over the fixed `GRID_STEPS_MM` ladder, a snap
  on/off switch, three symmetry axis toggles. All of `ModellingGrid` is booleans plus one
  enum-like discrete value — there is no numeric-entry design problem here at all.
- **Modifier stack as "layers"**: a flat enable/reorder list over the existing
  `MeshModifierStack`/`updateMeshModifierStack` endpoint, labeled with Nomad's "layers"
  vocabulary per the brief's lesson 3(a).4, not feature-tree jargon.

**Deferred to increment 2, justified by dependency and by interaction-design cost, not
by F-086 priority:**

- **Surface-detail operations** (`detail` op: circle/square/ribs/knurl profiles, with
  mode raised/recessed and depth). Deferred because placing a dimensioned profile on a
  touch surface — exact diameter/pitch/rotation/area, not just "about here" — is a
  materially different and harder interaction problem than selecting/moving/extruding an
  existing component, and F-086 explicitly requires these carry "exact dimensions": a
  rushed touch design here is exactly where "fake precision on mobile the kernel doesn't
  provide" (the brief in the task context flags this risk directly) would first leak in.
  It deserves its own design pass once increment 1's selection/bottom-sheet patterns exist
  to build on.
- **Mesh→exact-CAD acceptance** (consuming `CadProfileResult`/`AnyCadProfileSeed` from
  T-247/T-248 — "select a planar/curved region, accept it as an exact sketch or analytic
  patch"). Not requested as a hard requirement by the task brief, and it is a strict
  superset of increment 1's selection baseline (it needs face selection to exist first,
  which increment 1 delivers) plus a new "structured result + confirm" bottom sheet
  (show recovered surface kind/radius/angle or the specific `CadProfileFailureCode`
  message, then "Use as exact CAD patch"). It is the **cheapest** candidate for
  increment 2/3 precisely because `cadProfileFromFaces` (`topology.ts:988`) is pure
  accept/reject with no dimensioned placement — see open question 4.
- **Sketch/loft/sweep/revolve/NURBS authoring** (`ExactCadPanel.tsx`'s full surface). Out
  of scope for any near-term mobile increment, not just increment 1: authoring NURBS
  control points, weights, knot vectors and per-segment direction/constraint toggles by
  touch is not a UI-layout problem to solve with bottom sheets, it is a fundamentally
  different input modality question (closer to "does this product want freehand/assisted
  curve drawing on mobile at all," a product decision, not a UX port).

**Explicit cut inside increment 1's own selection UX — no box/lasso drag-select.** Web's
`BoxSelectBridge` (`TopologyOverlay.tsx:155`) does a drag-rectangle → per-vertex
projection → optional occlusion raycast. On mobile, a one-finger drag is already claimed
by `outline`/`paint` path-drawing and by orbit; a two-finger drag is already claimed by
pan. Reusing either gesture for lasso-select would conflict with gestures users already
rely on in this same viewer. Increment 1 ships tap-accumulate multi-select only (toggle
chip + repeated taps); a drag-lasso is deferred and listed as open question 1, not
silently dropped.

## 2. UX architecture

**Screen-size reality check first.** `apps/mobile/app.json` sets `"orientation":
"default"` (not locked to landscape or tablet) and `"ios": { "supportsTablet": true }` —
this is a phone-and-tablet, both-orientation target, not an iPad-only canvas like Nomad's
original design surface. Every control below is sized and laid out for a phone's width
first; a larger screen gets the same stacked layout with more breathing room, not a
different layout (see open question 3 on whether that leaves value on the table for
tablets later).

**Entry point.** The existing viewer toolbar row already holds mode-toggle chips —
`Outline an area` / `Paint` (`project/[id].tsx:597-625`), which flip `ModelViewer`'s
`mode: DrawMode` prop (`"orbit" | "outline" | "paint"`). Increment 1 adds one more value,
`"edit"`, and one more chip, `Edit mesh`, in the same row — not a new screen, not a modal
takeover. This matches the existing pattern exactly (same `Pressable`/`styles.button`
components, same disabled-when-no-model guard) and avoids inventing a second navigation
model alongside the one `apps/mobile/app` already has (file-based routes for
project/scan/sign-in, not a separate "Studio mode" route).

**Component-kind picker.** A three-way segmented chip row (`Vertex · Edge · Face`),
visually identical to the existing `BRUSHES`/`PALETTE` chip rows already rendered in paint
mode (`project/[id].tsx:630-659`) — no new visual language, reuse of an established
pattern.

**Selection gesture.** One tap = `componentAtHit(topology, kind, hit)` → single pick,
replacing the selection (mirrors a plain click on web). A persistent `Multi-select`
toggle chip (bottom corner, thumb-reachable per the Nomad lesson on flat/reachable tool
access) switches subsequent taps to `applySelection`'s `"toggle"` mode instead of
`"replace"` — this is the direct touch analogue of a desktop ctrl/shift-click, without
needing a keyboard modifier that doesn't exist on a touchscreen. Selected components are
drawn with the same highlight-colour convention web already uses (`#ffb020` in
`TopologyLayer`) so a person moving between web and mobile sees the same "this is
selected" colour.

**Operation entry — flat row, not nested menus.** This is the direct application of the
brief's core lesson (3(a).3): "primary sculpt/mesh-edit tools... sit in a flat,
thumb-reachable... layer instead of nested menus." Once a selection of the right kind
exists, a flat row of operation chips appears above the keyboard-safe area — `Move`,
`Extrude`/`Inset` (face-only), `Bevel` (edge-only), `Delete` (face-only) — filtered to
what the current selection kind supports, exactly mirroring how `MeshEditPanel.tsx`
already gates its sections on `selection.kind` (`MeshEditPanel.tsx:68`, `request`/`kind`).
No nested "Edit → Mesh → Transform → Move" menu tree; one tap from selection to operation.

**Parameter entry — gesture-first, numeric as an escape hatch, not the other way round.**
This is the one genuinely new interaction increment 1 introduces (web's `MeshEditPanel`
has no drag/live-preview path at all for `move`/`extrude`/`inset`/`bevel_edges` — it is
numeric-field-then-Apply only, `MeshEditPanel.tsx:84-96`). For touch, numeric-field-first
is exactly the "web panel crammed onto a small screen" failure mode the task explicitly
warns against (the brief's critique of Hunyuan's thin mobile-web wrapper, Part 1.7). So
increment 1 instead makes the **drag itself** the primary input:

- Choosing `Move`/`Extrude`/`Inset`/`Bevel` opens a *thin* bottom sheet (reusing the
  `Modal` + transparent `Pressable` backdrop pattern already used by `CreateSheet.tsx:47`
  and the `quickEditOpen` modal in `project/[id].tsx:561-595` — no new sheet primitive to
  build) that shows only: the operation name, a live mm-value chip, and `Apply`/`Cancel`.
- A one-finger drag on the selected component (while the sheet is open — the viewport
  stays fully visible and interactive underneath the thin sheet, unlike web's permanently
  docked panel) scrubs the magnitude: along the face normal for `move`/`extrude`/`inset`,
  perpendicular-offset for `bevel_edges`'s width. `ModellingGrid.snap` (§ below), if on,
  rounds the live value to `step_mm` via the existing `snapPoint` helper before it is shown
  or committed — so snapping is visibly "the number jumps to clean mm values," not a
  hidden effect.
- The live mm-value chip is always visible during the drag (reusing the same bottom-left
  chip HUD pattern `ModelViewer.tsx:505-536` already renders for size/body-id/mode hints)
  — a person always sees the exact number they are about to submit, never just a visual
  guess. **Tapping that chip** opens a plain numeric `TextInput` (the same
  `keyboardType="decimal-pad"` pattern already used for dimensions and organic-size
  entry, `project/[id].tsx:877-882`) for exact-value entry — the escape hatch for anyone
  who wants to type `12.5` rather than drag to it. This satisfies both halves of the
  brief's lesson: touch-first for speed, keyboard precision never removed.
- `Delete` has no magnitude — its sheet is a single confirm/cancel, immediate.

**Grid/snap/symmetry — a separate, much simpler sheet**, reachable from its own chip
next to `Edit mesh` (not nested inside the edit-mode sheet, since it's relevant in orbit
mode too, e.g. to preview symmetry planes before entering edit mode): a horizontal
scroll-chip row over `GRID_STEPS_MM` (tap one to set `step_mm`, same row pattern as
`BRUSHES`), one `Snap` switch, three `X/Y/Z` symmetry toggle chips coloured to match
`SymmetryPlanes`' existing convention (`#ff5d6c`/`#52d273`/`#5b9cff`,
`TopologyOverlay.tsx:219`). No numeric keyboard appears anywhere in this sheet — every
value is a discrete pick, which is also why this slice is flagged in open question 2 as
a candidate to ship even before the rest of increment 1 if sequencing matters.

**Modifier stack — "Layers" sheet.** A flat list, each row a toggle switch + the
operation's localized label (reusing `MeshModifierStackPanel.tsx`'s `LABELS` map
verbatim) + up/down reorder arrows — the exact same affordances as the web panel, just
larger touch targets and sheet-presented instead of permanently docked. Labeled "Layers"
per the brief's lesson 3(a).4 recommendation to borrow Nomad's mental-model vocabulary
without changing the underlying typed stack.

**What this explicitly does not do**, to avoid the named anti-pattern: it does not
reproduce `MeshEditPanel.tsx`'s always-visible, fully expanded desktop panel sitting
beside a shrunk viewport; it does not port `ExactCadPanel.tsx`'s control-point/knot-vector
forms at all; every sheet is transient (appears for one decision, then closes), and the
3D viewport is never reduced to make room for a permanently docked side panel the way
desktop's layout works.

## 3. Precision/trust boundary, explicit

Every increment-1 operation submits through the identical `client.editMesh(versionId,
{ operations, tolerance_mm, label })` call web uses, and gets back the identical
`MeshEditReport` shape (`ok`/`code`/`message`/`before`/`after`/`warnings`/`repairs`,
`mesh-edit.ts:58-67`). Mobile shows the same `message` string on failure — never a
simplified "something went wrong" — and the same before/after `MeshStats` (faces,
vertices, volume, watertight) so a person can see the edit actually changed the mesh the
kernel reports, not just that the viewport redrew. **The kernel-side validation,
tolerance handling, and failure vocabulary are completely unchanged**; mobile adds a
touch front-end to an unchanged trust contract, exactly as the task requires.

Two places this boundary needs explicit care, because touch interaction pulls toward
casual/approximate input harder than a desktop form does:

1. **Grid/snap is an input aid, not an accuracy claim.** `snapPoint`/`ModellingGrid`
   round the *point the user is dragging to* before it becomes the operation's `delta_mm`/
   `distance_mm`/etc. — they never touch the kernel's own tolerance or claim the resulting
   geometry is "more exact" than an unsnapped value would be. The UI must never present
   "Snap: on" as a precision upgrade; it is a convenience for hitting clean round numbers
   with a thumb, and the live mm chip (§2) makes the actual submitted value visible
   either way, so there is no hidden rounding a person can't see before committing.
2. **Deferring surface-detail ops and CAD-profile acceptance is itself the trust
   decision, not an oversight.** These are precisely the two increment-1 candidates where
   a casual touch gesture could most plausibly end up labeled "exact" without being
   checked — a profile "roughly centered" by drag, or a mesh region "looks flat enough"
   accepted as an exact sketch without running `cadProfileFromFaces`'s real planarity/
   connectivity checks. Pushing both to a later increment, to be built with numeric-entry
   as primary (detail ops) or with the full `CadProfileFailureCode` message set surfaced
   verbatim (CAD acceptance) rather than a mobile-simplified accept button, is how F-086's
   "parametric CAD bodies keep using exact kernel operations instead of being silently
   degraded to a mesh" requirement stays true on mobile too, instead of being quietly
   relaxed because a phone screen is smaller.

## 4. Touch list

**No changes to `packages/contracts`** — every type and pure function increment 1 needs
(`MeshTopology`, `ComponentKind`, `buildTopology`, `componentAtHit`, `applySelection`,
`overlayEdges`, `MeshEditOperation`, `selectionToPoints`, `ModellingGrid`, `defaultGrid`,
`snapPoint`, `symmetricPoints`, `GRID_STEPS_MM`, `MeshModifierStack`,
`MeshModifierStackEdit`) already exists and is already platform-agnostic.

**No changes to any API/service/kernel code** — `editMesh`, `getMeshModifierStack`,
`updateMeshModifierStack` already exist in `packages/contracts/src/client.ts` and are
already callable from the `client` instance `apps/mobile` already holds.

**The one real gap found:** mobile's raycast hit object (`ModelViewer.tsx:265-278`,
`hitAt`) currently keeps `hit.point` and `hit.face.normal` but discards
`hit.faceIndex`, which `PickHit.sourceFace` (`topology.ts:263`) requires. This is a
one-line addition to an existing function (`return { ..., faceIndex: hit.faceIndex }`),
not a contract change — `faceIndex` is already present on every three.js `Raycaster`
intersection result, `hitAt` simply never read it before because outline/paint mode
never needed per-triangle identity, only a surface point and normal.

| File | Change |
|---|---|
| `apps/mobile/src/ModelViewer.tsx` | Add `"edit"` to `DrawMode`; keep `faceIndex` in `hitAt`'s return; build and cache a `MeshTopology` via `buildTopology` alongside the existing geometry-load effect (mirrors `apps/web/src/components/ModelViewer.tsx:647-663` almost verbatim); add direct-THREE wireframe/vertex-point overlay objects (port of `segmentGeometry`/`pointGeometry`/`faceGeometry` from `TopologyOverlay.tsx`, called from the existing `draw()` loop, not as React-three-fiber JSX since mobile manages the scene imperatively); add tap-pick-via-`componentAtHit` and a selection `Set<number>` plus `applySelection` wiring to the existing `Gesture.Tap`; add a one-finger drag-to-scrub handler for the active operation's magnitude, gated on `mode === "edit"` the same way `drawing` already gates outline/paint; render symmetry planes (port of `SymmetryPlanes`) when any `ModellingGrid.symmetry` axis is on |
| `apps/mobile/src/EditModeSheet.tsx` (new) | The operation-entry bottom sheet: component-kind chips, multi-select toggle, filtered operation-chip row, live mm-value chip + numeric escape-hatch `TextInput`, Apply/Cancel — built from the existing `Modal`+`Pressable` backdrop pattern (`CreateSheet.tsx:47`, `project/[id].tsx:561-595`), not a new sheet library |
| `apps/mobile/src/GridPanel.tsx` (new) | The grid/snap/symmetry sheet: `GRID_STEPS_MM` chip row, snap switch, X/Y/Z symmetry chips |
| `apps/mobile/src/MeshLayersSheet.tsx` (new) | Port of `MeshModifierStackPanel.tsx`'s toggle/reorder list to a bottom sheet, calling the already-existing `client.getMeshModifierStack`/`updateMeshModifierStack` |
| `apps/mobile/app/project/[id].tsx` | Add the `Edit mesh` and `Grid` toolbar chips next to the existing `Outline an area`/`Paint` row; own the new sheets' visibility state the same way `quickEditOpen` is already owned; wire `EditModeSheet`'s Apply to a new `runMeshEdit` function calling `client.editMesh(active.id, body)` through the existing `track()`/`headAfterJob()` helpers already used by every other mutating action on this screen (`send`, `applyPaint`, `resize`, `applyFix` all follow this exact shape already) |
| `apps/mobile/src/theme.ts` | Any new shared style tokens the sheets need beyond what `styles`/`colors` already export (symmetry-axis colours, selection highlight) — additive only |

No changes to `apps/mobile/app/_layout.tsx`, `index.tsx`, `scan/*`, `sign-in.tsx`,
`CreateSheet.tsx`, `EngineerCard.tsx`, `VoiceButton.tsx`, `capabilities.ts`, `photo.ts`,
`scan.ts`, `session.tsx`, or `modules/expo-room-plan` — none of this increment touches
scanning, capture, auth, or native-module territory. `modules/expo-room-plan` was checked
specifically per the task brief's instruction and confirmed irrelevant: that module exists
to bridge Apple RoomPlan's native capture session; mesh-edit/topology stays entirely in
the JS/expo-gl/three layer `ModelViewer.tsx` already runs in, the same way outline/paint
already do, so no native module bridging is needed here, matching the task brief's own
expectation ("it probably doesn't, since the kernel is server-side").

## 5. Proof plan

**What typechecking covers.** `apps/mobile/package.json` defines `typecheck`/`lint` as
the same `tsc -p tsconfig.json --noEmit` command (`package.json:9-10`) — there is **no
test runner configured in this package at all** (no Jest, no React Native Testing
Library, no dependency resembling one in `package.json`'s `dependencies`/
`devDependencies`). This is an honest starting fact, not a gap this increment can quietly
fix by inventing a parallel test stack the rest of the app doesn't have — adding one
would be its own decision, out of scope here.

**What's already covered by inheritance, not duplicated.** `buildTopology`,
`componentAtHit`, `applySelection`, `snapPoint`, `symmetricPoints`,
`cadProfileFromFaces`, and the rest of `topology.ts`'s pure functions are exercised by
`packages/contracts/test/topology.test.ts` already (run as part of the existing
contracts test suite, unaffected by this increment since none of their signatures
change). Mobile consuming them correctly is a typecheck-level guarantee (TypeScript
catches a wrong argument shape), not a behavioral one — the shared logic's *correctness*
is already proven elsewhere; what mobile-specific code needs proving is wiring and touch
feel, neither of which a unit test reaches.

**What genuinely needs a device/simulator, and why this is cheaper than the RoomPlan
precedent.** `docs/TZ_GAP_AUDIT_2026-09-21.md:11` records RoomPlan's native Swift module
as "не собран и не проверен на физическом LiDAR iPhone/iPad" — that gap exists because
RoomPlan requires a native module, an EAS development build, and physical LiDAR hardware,
none of which this increment needs. Every file in the touch list above is pure JS/expo-gl/
three, identical in kind to the `outline`/`paint` code already running today — so this
increment **can be fully exercised in Expo Go** on any phone or the iOS/Android simulator,
no dev build required. That said, the following can only be judged by actually running it,
not by typechecking, and must be stated as unverified until someone does:

1. **Touch-target size and reachability** — are the component-kind chips, multi-select
   toggle, and operation-chip row comfortably tappable at real phone screen widths and
   real thumb size, not just "fits in the simulator window"?
2. **Drag-to-scrub feel** — does a one-finger drag along a face normal feel like a
   sensible "move this much," or does the mm-per-pixel mapping need per-device tuning
   (likely yes, given phone screens vary in both size and pixel density far more than
   desktop displays)?
3. **Overlay performance** — `INTERACTION_EDGE_BUDGET` (60,000) and
   `MAX_VISIBLE_VERTICES` (120,000) are web/desktop-GPU-tuned constants
   (`topology.ts:99`, `TopologyOverlay.tsx:21`); whether those same ceilings hold up on a
   mid-range phone GPU inside `expo-gl` is an open, device-dependent question (see open
   question 5) — nothing on paper can answer it.
4. **Sheet-over-viewport legibility** — whether the thin bottom sheet truly leaves the
   selected component visible and draggable underneath it (the whole point of the
   gesture-first design in §2), or whether on a small phone it still ends up covering too
   much of the model, needs eyes on an actual device, not a mockup.

**Manual verification plan once built:** run in Expo Go on at least one phone-class
device (a mid-size Android or a non-Pro iPhone, not just a simulator or an iPad, given
§2's phone-first framing) and one physical tablet if available; walk every operation
(move/extrude/inset/delete/bevel) on a freshly generated test model through select →
drag → commit → confirm the resulting `MeshStats` in the response matches what the
viewport shows; toggle grid/snap/symmetry and confirm the live mm chip visibly jumps to
snapped values; reorder/disable a modifier-stack entry and confirm the rebuilt version
matches web's behavior for the same stack. None of this is claimed done until it is
actually run — same honesty standard the RoomPlan gap is held to.

## 6. Open questions for the owner

1. **Is tap-accumulate multi-select sufficient for increment 1, or does F-086's
   "selection" ambition require at least a simple lasso/drag-select on mobile before this
   can be called done?** A drag-lasso is deferred here specifically because every
   one-finger and two-finger drag gesture in this viewer is already claimed (orbit, pan,
   outline/paint drawing); adding one would need either a new gesture (e.g.,
   two-finger-tap-then-drag) or reclaiming an existing one, which is a product/UX call,
   not a purely technical one.
2. **Should grid/snap/symmetry ship as an even-earlier, standalone slice ahead of the
   rest of increment 1?** It has zero numeric-input design risk (pure toggles/chips) and
   no dependency on the selection/edit machinery — it could land and be verified on
   its own before the heavier drag-to-scrub mesh-edit UX is built on top of it.
3. **Tablet-specific layout.** `app.json` already declares `supportsTablet: true`, and
   iPad is literally Nomad's native surface — should increment 1 (or a fast-follow)
   add a side-panel layout variant for tablet widths instead of the same stacked
   phone layout everywhere, to make better use of the larger screen the way Nomad itself
   does? This design deliberately stays phone-first per the task's instruction but flags
   the tablet opportunity explicitly rather than silently ignoring it.
4. **Where does CAD-profile acceptance (T-247/T-248 consumption) actually land?** §1
   argues it's the cheapest post-increment-1 candidate since it's accept/reject rather
   than dimensioned placement — should it be folded into increment 2 alongside surface
   details, or deserve its own increment 3 given it's a genuinely different UI shape
   (a result-confirmation sheet, not an operation-parameter sheet)?
5. **Phone-GPU overlay budget.** Should `INTERACTION_EDGE_BUDGET`/
   `MAX_VISIBLE_VERTICES`-equivalent ceilings for mobile be lower than web's current
   constants, and if so by how much? This needs on-device profiling this design pass
   cannot produce on paper — flagged so it isn't silently inherited as "web's number is
   fine" without anyone checking.
