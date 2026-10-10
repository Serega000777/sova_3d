# Mobile plan editor (design)

Status: design only, no code. Picks up the deferral recorded in `docs/IN_PROGRESS.md`'s
10.10.2026 scoping note and item 12/13 in `docs/COMPETITOR_UI_ANALYSIS.md`'s "Полный
сценарий Sova 01–20" table. That note found the annotation model and business logic
(`hitTest`/`moveAnnotation`/`nextPinNumber`/`cloudPath` in
`packages/contracts/src/floor-plan.ts`) already platform-agnostic, and named the real
blocker as `apps/web/src/app/plan/page.tsx`'s concurrency-sensitive save/merge/undo code
— not something to port by analogy without a design pass. This document is that pass,
grounded in reading `apps/web/src/app/plan/page.tsx`, `apps/web/src/components/
PlanEditor.tsx`, `packages/contracts/src/floor-plan.ts`/`client.ts`/`live.ts`, and
mobile's existing `PlanViewer.tsx`/`WorkspaceShell.tsx`/`plan-link.ts`/`project/[id].tsx`
directly, not from memory of what they probably contain.

## 0. The real shape of the gap

**Confirmed, not assumed: no `packages/contracts` or API change is needed.** Every
annotation type, pure function (`hitTest`, `moveAnnotation`, `nextPinNumber`,
`cloudPath`, `annotationBounds`, `parseAnnotations`, `mergeAnnotationChanges`,
`formatLength`, `distanceBetween`) and the `History<T>`/`commit`/`undo`/`redo` helpers
in `floor-plan.ts` take and return plain data, with zero DOM/React dependency.
`client.ts`'s `getPlanAnnotations`/`putPlanAnnotations` (CAS via `base_revision`, 409 on
conflict) and `liveRoom` (`plan_annotations` is already a typed `LiveEvent` member,
`live.ts:26`) are already generic `fetch`/WebSocket calls mobile already holds a
`client` instance for. This matches `docs/design/MOBILE-CAD-PANELS-increment1.md`'s
finding for mesh-edit almost exactly: the gap is `apps/mobile` UI work consuming
machinery that already agrees, byte-for-byte, with web.

**One finding this design pass turned up that the original scoping note didn't call
out: mobile renders zero annotations today.** `apps/mobile/src/PlanViewer.tsx` (used by
`WorkspaceShell`'s Plan↔Model split, shipped in `e7b6575`) draws rooms, walls and wall-
junction nodes for 3D-link selection — it never touches `Annotation[]` at all. So "add a
mobile plan *editor*" is actually two layers stacked: render the markup other people
already made (a prerequisite with no standalone acceptance value — a read-only pass
would just be a confusing partial feature), then let mobile create/move/resolve it.
Both layers are scoped together into increment 1 below rather than split, because
shipping render-only first has no user-facing acceptance criterion of its own.

**Existing mobile precedent this design reuses instead of inventing new patterns:**
- `AsyncStorage` is already the mobile persistence idiom (`session.tsx`, `Onboarding.tsx`,
  `scan/index.tsx`'s resume key) — the offline fallback below is one more namespaced key,
  not a new mechanism.
- `apps/mobile/app/project/[id].tsx` already opens exactly one `client.liveRoom(id, ...)`
  per project and branches on `event.type` (`welcome`/`join`/`leave`/`cursor`/`note`/
  `version`, lines 339–362) — `plan_annotations` is one more branch on that same socket,
  not a second connection.
- `ModelViewer.tsx` already composes `Gesture.Pan`/`Gesture.Pinch`/`Gesture.Tap`/
  `Gesture.LongPress` from `react-native-gesture-handler` (lines 1027–1195) for
  simultaneous pan/pinch/tap/drag in 3D — the right tool to reuse for a 2D annotator's
  gesture surface instead of a second gesture idiom alongside it.
- A single-line transient `notice` banner (`project/[id].tsx:164`, already fed by the
  `version` live event at line 357–361) is the established "something happened, tell the
  user" pattern — reused verbatim below, not redesigned.

## 1. Annotation subset for v1

**Ship 7 of 8: pin, text, rect, cloud, circle, arrow, dimension. Defer: freehand.**

This is not "port the easy half, defer the hard half" by annotation count — it follows
from what the code actually shares. Web's own `dragShape()` (`PlanEditor.tsx:410–423`)
already treats `rect`/`cloud`/`circle`/`arrow`/`dimension` as **one gesture family**: tap
a start point, drag to an end point, release commits — differing only in which render
branch runs and how `from`/`to` maps to geometry (bbox, scalloped bbox, radius-from-
distance, line-with-arrowhead, line-with-length-label). `hitTest`, `moveAnnotation` and
`annotationBounds` are already written generically over this same union. So the
dominant cost here isn't five separate interaction designs — it's building **one** shared
two-point-drag gesture with snap, then five small SVG render branches. Cutting three of
the five and keeping two would be an arbitrary line, not a principled one; there's no
touch-interaction reason circle is "in" while arrow is "out" once the shared gesture
exists.

**Pin** is the cheapest of all (single tap, single point, no drag phase) and is also the
structural anchor of the existing "Замечания" sidebar — pins are numbered
(`nextPinNumber`) and the list UI is built around them. It ships regardless.

**Text** needs one more affordance class — a keyboard — but mobile already has the
matching UI primitive: a `Modal`+`Pressable` backdrop sheet (`CreateSheet.tsx`'s pattern)
with one `TextInput`. Marginal cost is "reuse an existing sheet," not a new primitive.

**Dimension deserves a specific call-out as the highest field value of the seven.** It's
the "stand in the room, tap wall to wall, read the number back" use case — the one this
repo's own measurement/placement raycast flows and competitors' tape-measure-replacement
features already prove works on touch. Snap-to-corner/wall here isn't just convenience
the way it is for a rect or cloud — it's the trust mechanism a construction user will act
on, so the live length label must stay visible for the whole drag, never only after
release (same rule as `MOBILE-CAD-PANELS-increment1.md` §3's live mm chip: snap is an
input aid, never presented as a precision upgrade).

**Freehand is excluded as a different *class* of problem, not a harder version of the
same one.** The other seven need 1–2 discrete point placements, each of which benefits
from the plan's existing snap-to-geometry. Freehand demands sustained legible fine-motor
control across an entire stroke with a bare fingertip (no stylus requirement in this
flow) — a materially different and harder interaction problem. It also inherits an
existing rough edge that would get worse, not better, on noisier phone touch sampling:
web's freehand draft pushes every raw pointer-move sample with no simplification
(`points: [...d.points, point]`, `PlanEditor.tsx:496`) — mobile would need its own point-
decimation story before shipping this, which is new design work, not a port. This repo
already drew exactly this line once before, in the same codebase, for the same reason:
`docs/design/MOBILE-CAD-PANELS-increment1.md` shipped box-select first and gave freehand
lasso-select its own dedicated follow-up increment. Same discipline applies here —
freehand is a named later increment (§7), not a silently dropped capability.

## 2. Concurrency/save model for mobile

**Same contract, same endpoint, same CAS — confirmed, no change.**
`getPlanAnnotations`/`putPlanAnnotations(projectId, planId, annotations, baseRevision)`
(`client.ts:474–493`) and the `PlanAnnotationsOut` revision discipline are already
platform-generic HTTP; mobile calls the identical methods. `mergeAnnotationChanges`
(`floor-plan.ts:511–542`) is reused verbatim for the three-way merge.

**One deliberate behavior change from web, not a blind port — commit coalescing.**
Web's move-gesture path calls `onChange()` (a `history` commit) on **every** pointermove
frame during a drag (`PlanEditor.tsx:507`), not once on release. That means every
intermediate pixel of a drag becomes its own undo step, and the save-debounce timer
resets every frame, so a slow drag can delay the autosave indefinitely while a fast flick
still fires many commits. Mobile's gesture handler instead coalesces a full drag/resize
gesture into **exactly one commit on gesture-end** (RNGH's `onEnd`), using local draft
state for the live preview during the drag. This is a correctness decision, not just a
performance one: on touch, "drag this pin here" is one mental action, and undo should
undo that whole action — not one of fifty sub-pixel steps — and it also means the
debounced PUT fires once per real edit instead of dozens of times per drag, which matters
more on a connection where every attempt has real latency and battery cost.

**Debounce window: keep 800 ms, as a value, not an assumption to re-derive.** Mobile
defines its own constant (the web constant `SYNC_DEBOUNCE_MS` is page-local to
`apps/web/src/app/plan/page.tsx:67`, not exported) at the same value. A shorter window
buys nothing when round-trip latency dominates cost on cellular; a much longer window
raises the exact lost-edit risk this feature exists to avoid in a multi-collaborator
scene. There's no information in this design pass to justify moving it either direction
without on-device measurement — flagged in §6, not pre-tuned here.

**409 conflict UX — correcting a premise, not designing a new screen.** Reading
`reconcileRemote` (`plan/page.tsx:234–266`) shows web's actual 409 experience is **not**
a side-by-side resolution UI that needs shrinking for a phone: it auto-merges
three-way (local wins true conflicts) and only ever surfaces a single-line `setMessage`
string — the same transient-text pattern as every other notice on that page. There is no
modal, diff view, or per-field choice to port. What genuinely doesn't fit mobile as-is is
narrower: web keeps a **permanent** status chip in its header
(`plan/page.tsx:613–621`, "Synced" / "Waiting to merge" / "Synced · live") — header space
`WorkspaceShell`'s project name + version label + view-mode segmented control already
fills, with nothing to spare.

Mobile design: reuse the existing `notice` banner (`project/[id].tsx:164`, already fed by
the `version` live event at 357–361) for the human-readable merge announcement, plus one
small persistent status **glyph**, not text — a dot next to the Plan↔Model toggle chip:
grey (synced), amber (debounced, not yet sent), red (waiting to merge / last PUT failed)
— tappable to re-surface the last notice on demand instead of permanently occupying
header width. The live-socket wiring is one more `event.type === "plan_annotations"`
branch on the project screen's already-open `liveRoom` (mirroring the existing `version`
branch at `project/[id].tsx:357–361`), not a second connection — web's separate plan-page
`liveRoom` call (`plan/page.tsx:270–292`) exists only because web's plan page is a
separate route from its Studio page; mobile has no such split to replicate.

**Offline/local fallback — a decision, not a simplification.** Mobile gets its own
`AsyncStorage`-backed copy, matching web's `localStorage` fallback in spirit: a
device-local copy is the resilience layer, the server is the source of truth once a
project is chosen. This is not "fail-closed, don't bother" — the established mobile
precedent (`session.tsx`, `Onboarding.tsx`, `scan/index.tsx`'s resume key) already uses
`AsyncStorage` for exactly this "don't lose local state across app restarts/kills" job,
so matching it here costs one more namespaced key (`sova.plan.annotations.${planId}`,
mirroring `notesKey()` at `plan/page.tsx:65`), not a new mechanism. It diverges from full
parity only where web's own guard already diverges: once a project is chosen, the
AsyncStorage copy is a warm-start snapshot for before the network round-trip resolves,
never a competing source of truth once the server answers (same `loadedServerKey` guard
web already has). Offline-with-a-project-chosen reads: the dot turns red, the notice says
the edit is kept on-device but not yet saved, and the next successful foreground/
reconnect runs the normal CAS+merge cycle once. A fail-closed "can't save, don't lose
your edit" that *discards* on exit would be dishonest marketing for the opposite of what
it says — losing a pin or dimension typed in a room with no signal is the single worst
outcome for exactly the field use case (on-site markup) that makes this feature valuable.

## 3. Undo/redo on mobile

**Decision: bounded one-step undo/redo for plan markup in v1**, matching the mobile-wide
one-step undo/redo gap `docs/IN_PROGRESS.md` already names as an open mobile remainder,
rather than porting web's full `past`/`future` stack UI. The underlying `History<T>`
type and `commit`/`undo`/`redo`/`HISTORY_LIMIT` helpers (`floor-plan.ts:399–426`) are
reused unchanged — v1 keeps committing to the full `History` value (so a later increment
can light up multi-step undo/redo with zero data-model change) but only exposes the most
recent step in the UI (`history.past.slice(-1)`-worth of usable undo). This is a UI-scope
decision, not a contract limitation, and is explicitly staged (§7), not a dead end.

Why not ship full parity now: once §2 coalesces each gesture into one commit, "undo"
has an unambiguous, legible meaning — undo the last placed/moved/deleted annotation,
exactly once. Multiple undo steps need their own legible affordance to be worth the
screen space (web's answer is two toolbar buttons users already understand from desktop
conventions); on a phone, "tap undo six times to find where you meant" is a worse
experience than instant, obvious one-step recovery, and nothing in this design pass shows
multi-step is actually needed yet. Redo mirrors undo for the same single step.

## 4. Touch interaction design

Same vocabulary as `MOBILE-CAD-PANELS-increment1.md`: gesture-first placement, a numeric/
keyboard escape hatch never removed, sheets instead of a permanently docked panel, a
live value always visible before commit.

**Shared gesture surface.** One `GestureDetector` composing `Gesture.Pan` (draw / move /
pan-the-view) + `Gesture.Pinch` (zoom) + `Gesture.Tap` (select / place point-kinds),
mirroring `ModelViewer.tsx`'s `Gesture.Simultaneous(Gesture.Race(tap, longPress, pan),
pinch)` composition instead of a second gesture idiom in the same app. A second finger
always cancels whatever one-finger gesture was starting and begins a pinch (ported as-is
from `PlanEditor.tsx:433–440`, which already resolves one-vs-two-finger ambiguity
correctly for a flat 2D canvas).

**Tool row.** A horizontal scroll-chip row — Select · Pan · Pin · Cloud · Rect · Circle ·
Arrow · Text · Dimension — same pattern as the existing `GRID_STEPS_MM`/`BRUSHES` chip
rows. Nine chips is fine precisely because the row scrolls; chip count doesn't change
per-chip reachability, the same conclusion `MOBILE-CAD-PANELS-increment1.md` already
reached for its operation-chip row.

**One-finger drag dispatch**, mirroring web's three-way `onPointerDown` switch
(`PlanEditor.tsx:446–470`) re-expressed as RNGH callbacks: pan (Select/Pan tool, no hit),
move (Select tool, hit an existing annotation — drag starts immediately, no separate
"enter move mode" step), or draw (any annotation tool active).

**Per-kind placement:**
- **Pin** — tap commits immediately, no drag phase; numbered via `nextPinNumber`
  (unchanged). Select: tap within `hitTest`'s pin-specific tolerance (`tolerance_mm *
  1.5`, unchanged). Move: drag, coalesced to one commit on release (§2). Delete: via the
  selected-annotation action sheet's button, not a swipe gesture — a fat-finger drag near
  a pin must never read as an accidental delete.
- **Text** — tap places the (snapped) anchor, then opens a modal bottom sheet (one
  `TextInput` + Place/Cancel, `CreateSheet.tsx`'s pattern) instead of web's inline
  floating `<input>` positioned over the SVG. This is a deliberate departure from web:
  an inline input at scaled SVG coordinates fighting the OS keyboard for the bottom of a
  phone screen is exactly the "looked fine on desktop, breaks on phone" risk this design
  exists to catch. A sheet keeps the input in the same safe, keyboard-aware place no
  matter where on the plan the tap landed.
- **Rect / Cloud / Circle / Arrow / Dimension** (one shared gesture) — press at the first
  point, drag to the second, both snapped via the plan's existing wall/corner `snapTo`
  logic (ported unchanged, `PlanEditor.tsx:278–290`); a live preview follows the finger
  exactly like web's `draft` state; release commits one annotation, one history entry.
  Dimension keeps the live length label (`formatLength`, unchanged) visible for the
  entire drag, not only on release — the "always show the number before it's submitted"
  rule, because this is the kind field users will most directly act on as a measurement.
- **Select** (any kind) — tap within `hitTest`'s tolerance, scaled the same way web does
  (`10 * px`, mm-per-screen-pixel at current zoom). Whether that pixel-equivalent
  tolerance is comfortable for a fingertip rather than a mouse pointer is explicitly
  unverified — flagged in §6, not assumed fine.
- **Status / notes / photo attach / "show in 3D"** — these are buttons in web's sidebar
  too, not gestures; they stay buttons in the same selected-annotation bottom sheet this
  app already uses for "selected thing → sheet of actions," not reinvented as swipe or
  long-press gestures.

## 5. Touch list

**No `packages/contracts` changes** — confirmed by reading the file, not assumed:
`Annotation`/`AnnotationKind`/`FloorPlan`/`Point` types and every pure function this
needs (`hitTest`, `moveAnnotation`, `nextPinNumber`, `cloudPath`, `annotationBounds`,
`distanceBetween`, `formatLength`, `parseAnnotations`, `mergeAnnotationChanges`,
`newHistory`/`commit`/`undo`/`redo`, `ANNOTATION_COLOURS`) already exist and are already
platform-agnostic.

**No API/service changes** — confirmed: `getPlanAnnotations`/`putPlanAnnotations`/
`liveRoom` already exist in `client.ts`, already generic, and `plan_annotations` is
already a typed `LiveEvent` member (`live.ts:26`) that web already type-checks against.

| File | Change |
|---|---|
| `apps/mobile/src/PlanAnnotator.tsx` (new) | The 2D editor surface: keeps `PlanViewer.tsx`'s room/wall/node/opening rendering and **adds** annotation rendering (new RN-SVG branches — `Rect`/`Circle`/`Path`/`Polyline`/`Line`/`Text` — porting `AnnotationShape`'s switch 1:1 from `apps/web/src/components/PlanEditor.tsx:155–237`, pure SVG geometry with no DOM API involved), the `GestureDetector` composition (§4), tool-row and draft/preview state, and the one-step-undo-aware commit dispatch (§2/§3) |
| `apps/mobile/src/PlanToolSheet.tsx` (new) | The text-entry sheet and the per-selected-annotation action sheet (note field, status toggle, delete, photo attach reusing the existing upload flow in `project/[id].tsx`, "show/place in 3D" deep link adapting `plan/page.tsx`'s `studioHref` pattern to mobile navigation) |
| `apps/mobile/src/plan-sync.ts` (new) | The debounced-CAS-save + 409-merge + `AsyncStorage`-fallback state machine as a hook (`usePlanAnnotationSync`), a direct port of `plan/page.tsx`'s effects (lines ~183–338) kept out of the (already large) project screen so it's testable in isolation from React Native rendering |
| `apps/mobile/app/project/[id].tsx` | Add the `plan_annotations` branch to the already-open `client.liveRoom` handler (mirrors the existing `version` branch, lines 357–361); own `PlanAnnotator`'s selection/tool state the same way `quickEditOpen`/`mode` are already owned; feed the sync-status dot + merge notice into the existing `notice`/`busy`/`error` line (1423–1424) |
| `apps/mobile/src/WorkspaceShell.tsx` | The `planViewer` slot's consumer becomes `PlanAnnotator` where editing is allowed (no structural layout change — the plan pane already has its own slot in both the tablet split and the phone `2D` tab) |
| `apps/mobile/src/theme.ts` | Additive only, if any annotation-colour token isn't already covered by the contracts-exported `ANNOTATION_COLOURS` — same precedent `MOBILE-CAD-PANELS-increment1.md` already set for this file |

No changes to `packages/contracts`, `services/api`, or `apps/mobile/modules/
expo-room-plan` (unrelated native capture module — same reasoning
`MOBILE-CAD-PANELS-increment1.md` already applied to it).

## 6. Proof plan

**Typecheck/build covers:** every new file is plain TS/React Native/`react-native-svg`/
`react-native-gesture-handler`, the same stack `ModelViewer.tsx`/`WorkspaceShell.tsx`
already use; `apps/mobile`'s `tsc -p tsconfig.json --noEmit` (no test runner configured
in this package, same confirmed fact as `MOBILE-CAD-PANELS-increment1.md` §5) catches a
wrong call shape against contracts' exported types.

**Covered by inheritance, not duplicated:** `hitTest`/`moveAnnotation`/`nextPinNumber`/
`cloudPath`/`mergeAnnotationChanges`/the `History<T>` helpers are exercised by
`packages/contracts`'s own test suite already; mobile calling them correctly is a
typecheck-level guarantee, not new proof the shared logic itself is right.

**Needs a physical device, not a simulator:**
1. Whether `hitTest`/`snapTo`'s mouse-tuned pixel tolerances are comfortable for a
   fingertip at real screen density, or need a larger effective radius on mobile.
2. Drag-to-draw feel for the five two-point kinds along a thumb's natural arc rather
   than a mouse's straight line, and whether the live preview keeps pace with finger
   speed on mid-range Android GPUs rendering an SVG-heavy plan.
3. Gesture disambiguation under real multi-touch noise (a resting palm, an edge touch)
   that a simulator's clean pointer input never produces, feeding the one-vs-two-finger
   dispatch in §4.
4. Keyboard-safe-area behavior for the text sheet, which differs enough between iOS and
   Android to need both platforms checked, not one.

**Needs real multi-device/multi-session testing, specifically for the concurrency
paths** — this is exactly where "looks fine in isolated testing" hides bugs, per the
task's own warning:
1. Two phones (or a phone and a web tab) editing the same plan concurrently, including
   one mid-drag (commit held until release, §2) while the other's PUT lands — does the
   eventual merge correctly treat the still-uncommitted local drag as "ours" once it
   finally releases, or can an incoming event stomp a gesture that hasn't committed yet?
   This needs a real second writer, not a mocked `LiveEvent`.
2. A real network drop-and-recover during an active drag or the debounce window — does
   the `AsyncStorage` snapshot survive an app **kill** (not just backgrounding) mid-edit,
   and does the next launch resume the CAS cycle from the last known revision instead of
   either discarding the offline edit or double-submitting it?
3. The `plan_annotations` live event racing the local debounced PUT's own response — the
   exact ordering `reconcileRemote`'s revision guards exist to prevent
   (`plan/page.tsx:237–238`) — re-verified against mobile's own hook rather than assumed
   to transfer, since React Native's effect-cleanup/unmount timing can differ from the
   browser's.
4. Backgrounding mid-drag or mid-debounce on both iOS and Android (which suspend JS
   timers differently) — does the pending PUT fire promptly on foreground, or get safely
   superseded by the next real edit, with no silent loss of the last unsent edit.

None of the above is claimed verified by this design pass; it's written down so it gets
checked, not silently assumed inherited from web's behavior on a different network and
runtime.

## 7. Staged delivery order

1. **Increment 1 (this document's scope):** render existing `Annotation[]` on mobile for
   the first time (§0's confirmed-missing prerequisite) + place/select/move/delete for
   pin/text/rect/cloud/circle/arrow/dimension (§1) + coalesced one-step undo/redo (§3) +
   the same CAS/409/merge contract reused unchanged (§2) + `AsyncStorage` fallback (§2) +
   the `plan_annotations` branch on the already-open live room (§2) + sync-status dot and
   notice banner (§2). Acceptance, in the same format as `LINKED-2D-3D-REFERENCE-
   WORKSPACE.md`'s MVP acceptance list: opening a project with existing web-authored
   markup shows the same pins/shapes on mobile; placing/moving/deleting on mobile
   round-trips through the same endpoint and is visible on web after a refresh or live
   update; a forced 409 (two simultaneous editors) ends in the documented merge+notice
   behavior, never a silently lost edit; killing the app mid-edit with no network
   preserves the unsent edit and resumes correctly on relaunch.
2. **Increment 2:** freehand annotation — its own gesture and point-decimation design,
   following the same box-select-then-lasso staging this repo already used for mesh-edit.
3. **Increment 3 (only if device testing shows it's actually felt as a limitation):**
   multi-step undo/redo for plan markup — the data model is already ready for this with
   zero migration (§3); not pre-committed here.
4. **Later/unscheduled:** any tablet-specific split-pane markup affordances beyond what
   `WorkspaceShell`'s already-shipped Plan↔Model split provides (this document only adds
   editing inside the pane that split already renders, it doesn't change the split
   itself); cross-referencing a mobile plan dimension against a 3D measurement is a new
   idea outside F-087's original scope and is not part of this plan.
