# Mobile CAD/mesh-edit/topology panels — tablet layout variant (design)

Status: design only, no code. Extends `docs/design/MOBILE-CAD-PANELS-increment1.md`
("increment 1"), which shipped as `935d761`/`b8c2e01` and deliberately stayed
phone-first, flagging tablet as open question 3:

> Tablet-specific layout... should increment 1 (or a fast-follow) add a side-panel
> layout variant for tablet widths instead of the same stacked phone layout everywhere?

The owner's answer (2026-10-08): gesture-first/Nomad-style interaction extends to
**both phone and tablet**, and explicitly **not** to desktop/web, which keeps its
existing docked-panel, mouse/keyboard UI exactly as shipped. This document designs
that tablet variant. It does not revisit increment 1's scope cut (no `detail` op, no
CAD-profile acceptance, no lasso-select) — those decisions are unchanged and orthogonal
to layout.

## 0. What this is, in one paragraph

This is a responsive-layout variant of the four increment-1 files
(`EditModeSheet.tsx`, `GridPanel.tsx`, `MeshLayersSheet.tsx`, and the toolbar/viewport
wiring in `project/[id].tsx`), keyed off a width breakpoint read with React Native's
own `useWindowDimensions()`. No contract types, no API calls, no gesture logic in
`ModelViewer.tsx`, and no selection/edit/grid/layers business logic change. The only
new code is: one shared hook/constant for "is this a tablet," one shared presentational
shell that the three existing sheets adopt instead of each duplicating their own
`Modal`+`Pressable`+`View` boilerplate, and width-conditional style values passed into
that shell and into `ModelViewer`'s `height` prop.

## 1. Breakpoint

**`apps/mobile` has no existing responsive-layout code today** — grep across `src/`
and `app/` for `useWindowDimensions`, `Dimensions`, `isTablet`, `breakpoint` found
nothing except `app.json`'s `"ios": { "supportsTablet": true }` declaration itself.
There is no prior pattern to match; `useWindowDimensions()` is React Native's own
built-in hook (already available via the `react-native` dependency already in
`package.json`, no new package), so this design uses it rather than introducing
`Dimensions.get` (which doesn't re-render on rotation) or a third-party breakpoint
library.

**Threshold: `Math.min(width, height) >= 600` (density-independent pixels).**

- Using the *shorter* side, not raw `width`, means the classification doesn't flip
  between "tablet" and "phone" purely from rotating the device — relevant here because
  `app.json`'s `"orientation": "default"` (unchanged, not locked) means both phone and
  tablet can be in either orientation.
- `600dp` is Android's own tablet qualifier convention (`sw600dp`, the resource
  qualifier Android itself uses to mean "tablet-class device," used by Google's Material
  Design guidance as the standard phone/tablet split). It is a well-documented,
  citable threshold rather than a number invented for this doc.
- It cleanly separates the two device classes that matter here: the largest current
  phones (e.g. a 6.7" phone) have a shorter side around 410-430dp even accounting for
  RN's density-independent points, well under 600; the smallest tablets Apple and
  Android both ship (iPad mini at 744pt shorter side, most Android "7-8 inch" tablets)
  sit at or above 600dp. There is no real device class that lands ambiguously between
  phone-sized and this threshold.

```ts
// apps/mobile/src/layout.ts (new)
import { useWindowDimensions } from "react-native";

export const TABLET_BREAKPOINT_DP = 600;

export function useIsTablet(): boolean {
  const { width, height } = useWindowDimensions();
  return Math.min(width, height) >= TABLET_BREAKPOINT_DP;
}
```

This is a plain hook in its own single-purpose file, matching the existing convention
of small focused files under `src/` (`capabilities.ts`, `photo.ts`, `session.ts`) rather
than folding a hook into `theme.ts`, which today only exports `colors`/`styles` data,
not behaviour.

## 2. What changes at tablet width, and why

**Starting point, read from the shipped code, not assumed from the design doc:**
`project/[id].tsx` renders `ModelViewer` (default `height=320`) and the toolbar chip
row (`Outline an area` / `Paint` / `Edit mesh` / `Grid` / `Layers`) as two blocks
stacked vertically inside one page-level `ScrollView`, alongside every other project
block (prompt box, photo picker, chat, version history — unrelated to this task).
`EditModeSheet`, `GridPanel`, and `MeshLayersSheet` are each an independent
`Modal transparent` with: a full-screen `Pressable` backdrop at `rgba(0,0,0,0.18-0.45)`
that both dims the whole screen (including the viewport) and closes the sheet on tap,
and a content `View` pinned to the bottom edge at `width: 100%` and a `maxHeight`
percentage (42-58% depending on the sheet).

**The concrete tablet change: these three sheets stop being full-width, full-dim,
bottom-anchored overlays and become narrower, undimmed, corner-docked floating panels
— same trigger chips, same state, same content, same Apply/Cancel/backdrop-tap-to-close
behaviour.** Nothing about the interaction model changes (still tap-to-select,
drag-to-scrub, chip-based operation entry, numeric escape hatch) — only the geometry
and dimming of the overlay that hosts it.

Concretely, keyed on `useIsTablet()`:

1. **No full-screen dimming.** The backdrop `Pressable`'s `backgroundColor` becomes
   `"transparent"` instead of the current `rgba(0,0,0,0.18-0.45)`. It still exists and
   still closes the sheet on tap (so "tap outside to dismiss" is unchanged), but it no
   longer visually darkens the model. This is the change that actually delivers "never
   permanently hides the viewport" at tablet width — a geometrically narrow panel that
   sits on top of a dimmed full screen would still visually bury the model under a dark
   overlay, which is exactly the thing increment 1's §2 explicitly designed against.
2. **Docked, not full-width.** The content `View` gets `width: 420` (clamped to the
   window width minus margin on a borderline-sized device) instead of `width: "100%"`,
   `alignSelf: "flex-end"` inside a backdrop `View` whose `alignItems` becomes
   `"flex-end"`, and rounded corners on all four sides instead of only the top two (a
   floating card, not a sheet sliding up from the screen edge). It stays anchored to the
   bottom-right corner — the same "bottom corner, thumb-reachable" placement increment
   1 already chose for the multi-select toggle chip (§2), kept consistent here rather
   than introducing a second placement convention.
3. **More height where the content is a scrolling list.** `MeshLayersSheet`'s
   `maxHeight` becomes `"72%"` on tablet (from `"58%"`) — its content is a
   vertically-scrolling modifier-stack list, so more height directly means more rows
   visible without scrolling, a literal instance of "a wider/taller sheet shows more at
   once" instead of a cosmetic resize. `EditModeSheet` and `GridPanel`'s `maxHeight`
   stay at their current percentages (`48%`/`42%`) — their content is chip rows and
   switches that don't benefit from extra height the way a list does, so there is no
   manufactured justification to change that number.
4. **The viewport itself gets taller.** `ModelViewer`'s `height` prop, passed from
   `project/[id].tsx`, becomes `isTablet ? 520 : 320`. This is the one change outside
   the sheets: a tablet's screen has materially more vertical room than a phone's, and
   increment 1's whole thesis (§2, "the 3D viewport is never reduced... the way desktop's
   layout works") argues for giving the model more screen, not holding it at a
   phone-tuned constant once more room exists.

**What does not change, and why — read from the shipped chip labels, not assumed:**
the subagent task brief suggested "does the component-kind/operation-chip row get more
room to show labels instead of icon-only?" as a candidate change. Checking
`EditModeSheet.tsx`'s `KINDS`/`OPERATIONS` tables: both already render full-word labels
("Vertex"/"Edge"/"Face", "Move"/"Extrude"/"Inset"/"Bevel"/"Delete"), not icons — there
is no icon-only state to upgrade. The toolbar row in `project/[id].tsx` (`Outline an
area`/`Paint`/`Edit mesh`/`Grid`/`Layers`) already uses `styles.row`'s `flexWrap: "wrap"`
and full-word labels too. Neither needs a tablet-specific change; inventing one here
would be exactly the "add complexity the task doesn't require" anti-pattern this
repo's own engineering guidance warns against.

**Explicitly out of scope for this design:** the rest of the project screen (prompt
box, photo picker, chat, version history, print-analysis card) stays a single-column
`ScrollView` on tablet exactly as it is today. This task is about the mesh-edit/grid/
layers panels and their relationship to the viewport, not a full tablet redesign of the
whole project screen's information architecture — that would be a much larger,
separate design decision this doc does not make on the owner's behalf.

**A deliberately deferred alternative, noted rather than built:** the task brief's
other suggested option was a *persistent* (always-visible, not transient) tool rail for
`EditModeSheet`'s selection controls, living beside the viewport at all times while in
edit mode, with only the magnitude/apply step staying a transient sheet. That is a
materially bigger change — it requires splitting `EditModeSheet`'s JSX into two
components (a persistent rail piece and a transient confirm-sheet piece) and
restructuring `project/[id].tsx`'s top-of-screen layout into a `flexDirection: "row"`
container on tablet. It is a legitimate idea for a later iteration if the docked-panel
version below ships and still feels too modal/interruptive in practice, but building it
now, on paper, without having first shipped and used the simpler docked-panel variant,
would be exactly the kind of unverified complexity this repo's guidance says to avoid.
It is listed as open question 1, not silently dropped.

## 3. Desktop/web — explicitly untouched

No file under `apps/web` changes. `MeshEditPanel.tsx`, `ExactCadPanel.tsx`,
`TopologyOverlay.tsx`, and `MeshModifierStackPanel.tsx` keep their existing
permanently-docked, numeric-form, mouse/keyboard UI exactly as shipped — the owner was
explicit that gesture/touch-oriented layout work is mobile-plus-tablet only, and PC's
existing panel-beside-shrunk-viewport pattern is intentional for a precise-input,
large-fixed-screen context, not a regression to fix. This document proposes nothing for
`apps/web`.

## 4. Reuse, not rebuild

No change to `packages/contracts` (same as increment 1 — this is purely
`apps/mobile` layout code) and no change to `ModelViewer.tsx`'s gesture handlers,
`hitAt`, `pickComponent`, or the `pan`/`pinch`/`tap`/`longPress` gesture rig — tablet
and phone share the exact same selection/drag-to-scrub/tap-pick code path. The only
`ModelViewer.tsx` change is the `height` prop value passed in from the caller (§2.4),
which the component already accepts as a prop — not a new capability.

The one new shared piece of UI code is a presentational shell extracted from the
Modal/Pressable/content-View pattern the three sheets each already implement
independently today (visible by comparing `EditModeSheet.tsx:99-117`,
`GridPanel.tsx:24-36`, and `MeshLayersSheet.tsx:104-116` — all three hand-roll the same
`Modal transparent` → full-screen `Pressable` backdrop → bottom-anchored content `View`
with `maxHeight`/`borderTopLeftRadius`/`borderTopRightRadius` structure). Extracting
that shared shell **once**, with the phone/tablet conditional living in exactly one
place, is less code and less duplicated conditional logic than adding the same
`isTablet` branching three times over three already-near-identical blocks — a
reduction in complexity, not an added abstraction layer for its own sake.

```ts
// apps/mobile/src/SheetShell.tsx (new) — shape, not final code
export function SheetShell({
  visible, onClose, maxHeightPercent, tabletWidth = 420, children,
}: {
  visible: boolean;
  onClose: () => void;
  maxHeightPercent: string;      // e.g. "48%", "58%", "72%" — sheet keeps its own value
  tabletWidth?: number;
  children: React.ReactNode;
}) {
  const isTablet = useIsTablet();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, justifyContent: "flex-end", alignItems: isTablet ? "flex-end" : "stretch" }}>
        <Pressable
          style={{ flex: 1, backgroundColor: isTablet ? "transparent" : "rgba(0,0,0,0.18)" }}
          onPress={onClose}
        />
        <View style={{
          width: isTablet ? tabletWidth : "100%",
          maxHeight: maxHeightPercent,
          borderRadius: isTablet ? 22 : undefined,
          borderTopLeftRadius: 22,
          borderTopRightRadius: 22,
          margin: isTablet ? 16 : 0,
          backgroundColor: colors.panel,
          borderColor: colors.border,
          borderWidth: 1,
          padding: 16,
        }}>
          {children}
        </View>
      </View>
    </Modal>
  );
}
```

Each of `EditModeSheet.tsx`, `GridPanel.tsx`, `MeshLayersSheet.tsx` keeps every line of
its actual content (chip rows, switches, the modifier list, the numeric escape hatch,
`Apply`/`Cancel`) unchanged, and only replaces its own hand-rolled
`Modal`/`Pressable`/outer-`View` wrapper with `<SheetShell>`.

## 5. Touch list

| File | Change |
|---|---|
| `apps/mobile/src/layout.ts` (new) | `TABLET_BREAKPOINT_DP = 600` and `useIsTablet()` (§1) |
| `apps/mobile/src/SheetShell.tsx` (new) | Shared Modal/backdrop/content shell (§4): undimmed + corner-docked + fixed-width on tablet, unchanged full-width/bottom/dimmed behaviour on phone |
| `apps/mobile/src/EditModeSheet.tsx` | Replace its own `Modal`/`Pressable`/outer-`View` (lines 99-117 today) with `<SheetShell visible={visible} onClose={onClose} maxHeightPercent="48%">`; no change to any chip row, the magnitude input, `Stats`, or `Apply`/`Cancel` |
| `apps/mobile/src/GridPanel.tsx` | Same shell swap, `maxHeightPercent="42%"`; no change to the step-chip row, `Snap` switch, or symmetry chips |
| `apps/mobile/src/MeshLayersSheet.tsx` | Same shell swap, `maxHeightPercent={isTablet ? "72%" : "58%"}`; no change to the modifier list, reorder buttons, or `Rebuild`/`Reset` |
| `apps/mobile/app/project/[id].tsx` | Pass `height={isTablet ? 520 : 320}` to `ModelViewer` (one new `useIsTablet()` call, one prop value); no change to any state, handler, or the toolbar chip row itself |
| `apps/mobile/src/theme.ts` | None required — `SheetShell` reads `colors`/`styles` as they already exist; no new tokens needed for this variant |

**No changes to:** `ModelViewer.tsx`'s gesture handlers/`hitAt`/`pickComponent`/overlay
building (only the `height` prop value changes at the call site, not inside the
component), `packages/contracts`, any `apps/web` file, any API/service/kernel code,
`apps/mobile/app/_layout.tsx`, `index.tsx`, `scan/*`, `sign-in.tsx`, `CreateSheet.tsx`,
`EngineerCard.tsx`, `VoiceButton.tsx`, `capabilities.ts`, `photo.ts`, `session.tsx`, or
`modules/expo-room-plan` — same boundary increment 1 drew, unaffected by a layout-only
change.

## 6. Proof plan

**What typechecking covers.** Same honest baseline as increment 1:
`apps/mobile/package.json`'s `typecheck` and `lint` scripts are both literally
`tsc -p tsconfig.json --noEmit` (`package.json:13-14`) — there is still no test runner
configured in this package (no Jest, no React Native Testing Library, nothing in
`dependencies`/`devDependencies` resembling one). `tsc --noEmit` will catch:
`SheetShell`'s prop types matching across all three call sites, `useIsTablet()`'s
return type, and the `ModelViewer` `height` prop still being a `number`. It will not
catch anything about how the layout actually looks or feels on a tablet-sized screen —
that is a UI-correctness claim, not a type-correctness one, and this plan does not
conflate the two.

**What genuinely needs a tablet-class device or simulator, and is not claimed done
without one:**

1. **The 600dp breakpoint boundary itself.** Nothing on paper proves `Math.min(width,
   height) >= 600` draws the line exactly where it should for every real device this
   product will run on (a borderline 7" Android tablet in particular) — it is a
   documented, reasonable convention (§1), not a measured one. Needs checking on at
   least one real small-Android-tablet or its simulator profile, not just an iPad
   simulator, which would only validate the comfortably-above-threshold case.
2. **Whether an undimmed, corner-docked panel actually reads as "floating panel," not
   "oddly placed small box."** This is a visual-design judgment a mockup or typecheck
   cannot make; it needs eyes on an iPad simulator/device at minimum, both orientations
   (`app.json`'s `orientation: "default"` means both are reachable).
3. **Whether 420dp is the right docked width and 520 the right viewport height**, or
   whether either needs tuning once seen next to real toolbar-chip and model content at
   tablet scale — flagged here as a first guess grounded in the sheets' current content
   (§2.2-2.4), not a measured final value.
4. **Rotation behaviour.** `useWindowDimensions()` re-renders on rotation by design, so
   the tablet/phone classification itself should update live without a remount — but
   whether an *open* sheet's position/sizing updates cleanly mid-rotation (versus
   needing to be closed and reopened) is a runtime behaviour, not something `tsc` can
   confirm.

**Manual verification plan once built:** on an iPad simulator (both orientations) and,
if available, a physical Android tablet near the 600dp boundary: open each of `Edit
mesh`/`Grid`/`Layers` and confirm the model stays visibly undimmed and interactive
around the docked panel; rotate the device with a sheet open and confirm it doesn't
end up mispositioned; confirm `MeshLayersSheet`'s taller tablet sheet actually shows
more rows than the phone sheet for a stack with 4+ modifiers; confirm the exact same
flow already verified for increment 1 on phone (select → drag → commit → confirm
`MeshStats`) still works unchanged on tablet, since no gesture code changed. None of
this is claimed done until it is actually run on the relevant hardware/simulator —
same honesty standard increment 1 and the RoomPlan gap are both held to.

## 7. Open questions for the owner

1. **Is the docked-floating-panel variant (§2) sufficient, or does the owner want the
   heavier persistent-rail variant (§2, "deliberately deferred alternative") sooner
   rather than as a possible fast-follow?** The persistent rail is a materially bigger
   change (component split + a `flexDirection: "row"` restructure of the top of the
   screen on tablet) that this design recommends building second, only if the simpler
   docked-panel version ships and still feels too modal in practice.
2. **Bottom-right dock, or does left-handed/stylus-in-left-hand usage argue for a
   configurable or bottom-left dock instead?** This design picked bottom-right purely
   for consistency with increment 1's existing multi-select-toggle placement (§2.2), not
   from any left/right-handedness research — a real open question if the owner has a
   preference or user data either way.
3. **Does the rest of the project screen (prompt/chat/version history) eventually want
   a tablet-specific two-column treatment too**, now that `useIsTablet()` exists as a
   reusable primitive? This design deliberately scoped that out (§2) as a separate,
   larger decision, not a layout detail of the mesh-edit panels.
