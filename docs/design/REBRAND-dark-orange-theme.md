# Rebrand: dark-orange default theme

Status: design doc, no product code touched. Owner mandate confirmed 2026-10-09 ~01:26-01:36 MSK
(see `memory/feedback_onboarding_visual_reference.md` in the architect agent workspace). Scope:
switch SOVA's default theme from dark-blue to dark-orange, redo onboarding to match, default
3D-viewer model color to white, keep cream-green as a deferred settings-togglable theme (do not
build it now).

**Important finding before anything else:** part of this rebrand already shipped, in the same
session, before this doc was written:

- `a711429` *feat(mobile): adopt Sova dark orange visual system* — rewrote
  `apps/mobile/src/theme.ts`'s `colors` object to the orange palette.
- `3ef0034` *feat(mobile): build adaptive editor workspace* and `7d8e46f` *docs: record adaptive
  mobile workspace* — `apps/mobile/src/WorkspaceShell.tsx` already consumes `colors.accent` etc.
  and renders orange throughout.
- The mobile port of onboarding, `apps/mobile/src/Onboarding.tsx` (not the one named in the task
  brief — see note below), is **already a complete dark-orange redo**: numbered steps, hero
  illustration area with an "orange glow," action rows, STL/3MF/GLB format chips, all pulling from
  `colors.*`.
- `apps/mobile/app/sign-in.tsx` imports `colors`/`styles` from `theme.ts` for everything except
  third-party OAuth brand buttons (VK blue, Yandex red/white — correctly left alone, those are
  Yandex/VK's own brand colors, not SOVA's). Because it never hardcodes hex values for its own UI,
  it inherited orange automatically when `theme.ts` changed.
- `apps/mobile/src/ModelViewer.tsx` already defaults uncolored geometry to an off-white
  (`#f3f1ec`), not orange, and derives its accent-colored selection/trail/symmetry overlays from
  `colors.accent` (now orange) rather than a hardcoded blue.

**This means mobile needs no further work for increment 1.** The remaining increment-1 work is
entirely on the **web app**, which still runs the original dark-blue palette end to end
(`apps/web/src/app/globals.css` `--accent: #5b9cff`, `apps/web/src/components/Onboarding.tsx`
still plain unicode glyphs on blue, `apps/web/src/components/ModelViewer.tsx` still blue
selection/hover). Below, "port the mobile pattern to web" is the operative instruction wherever
applicable — the mobile files are now the proven in-house reference, not the external mockups.

A note on file naming: the task brief said "web `Onboarding.tsx`, mobile port commit
`5440c6e`/`dffc005`" — that's accurate for the *first* mobile onboarding (now superseded). The
current mobile file is a full second pass (commit untitled in the `3ef0034`/adaptive-workspace
batch, AsyncStorage key bumped to `sova.onboarded.v2`). Treat the current `apps/mobile/src/Onboarding.tsx`
as canonical; the web file is the one still needing the equivalent treatment.

---

## 1. Dark-orange design-token system

### Web (`apps/web/src/app/globals.css` `:root`)

Current (dark-blue):
```css
--bg: #0f1115;
--panel: #171a21;
--panel-2: #1e222b;
--border: #2a2f3a;
--text: #e6e8ee;
--muted: #9aa3b2;
--accent: #5b9cff;
--accent-2: #2f6fd6;
--green: #35c48d;
--yellow: #e6b84a;
--red: #ef5d5d;
```

Proposed, matching mobile's already-shipped palette so web and mobile stop diverging:
```css
--bg: #0b0c0e;
--panel: #141517;
--panel-2: #1c1d20;
--border: #303033;
--text: #f5f2ed;
--muted: #aaa49d;
--accent: #ff6b1a;
--accent-2: #e9540b;
--accent-wash: rgba(255, 107, 26, 0.10);
--accent-wash-strong: rgba(255, 107, 26, 0.17);
--green: #35c48d;
--yellow: #e6b84a;
--red: #ef5d5d;
--viewport: #070809;
```

`--green`/`--yellow`/`--red` are reused as-is — they're semantic status colors (success/warning/
error), already distinct from the blue accent, and the owner's reference set uses an equivalent
green checkmark for the print-readiness "ready" state (see §4), so no change needed there. Adding
`--viewport` (the 3D canvas clear color, currently a bare `#0b0d12` hardcoded in `ModelViewer.tsx`
line 811) promotes it to a token for parity with mobile's `colors.viewport` and because dark-orange
reference renders use a near-black, not dark-navy, viewport.

Because `--accent` is referenced by ~50 selectors in `globals.css` already (nav links, buttons,
onboarding dots, hub tiles, scan progress, create-goal cards, export-format chips, etc.), swapping
the four `--accent`/`--accent-2` root values repaints most of the app automatically. What does
**not** auto-repaint, because it hardcodes the blue hex instead of using the variable, and needs
individual edits:

- `.topbar .brand-mark` (line 79): `linear-gradient(145deg, #294e86, #172b4b)` — this is the old
  logo block background; replace per the logomark plan below.
  `.topbar .brand-mark` color `#bfd9ff` (line 81) and `.topbar .brand b` color `#8fbfff` (line 84)
  likewise need a warm replacement (e.g. `--accent`/a light cream tint).
- `.topbar-create` (lines 112-126): `background: #2c69bf`, hover `#3579d7`, border
  `rgba(125, 178, 255, .52)`, shadow `rgba(20, 68, 153, .22)` — the primary "Создать" CTA button;
  swap to the accent/accent-2 pair.
- `.topbar-avatar` background `#365787` (line 138) — avatar chip, swap to a neutral panel tone or
  accent-tinted neutral (avoid literal orange avatar background, which would look like a
  notification badge; a muted warm grey reads better here).
- Several `rgba(91, 156, 255, …)` glows/washes that don't go through a variable: `.create-goal:hover`
  gradient (line 567), `.create-source.active` background/shadow (line 578), `.hub-icon` background
  (line 1866), `.library-thumb` gradient (line 1962), `.onboarding-icon` background (line 1972),
  `.guide-dot` box-shadow (line 1879 area), `.scan-progress` current-step shadow (line 1990),
  `.export-format.active` background (line 1947), `.auth-field input:focus` box-shadow (line 514).
  All of these should become `rgba(255, 107, 26, …)` at the same alpha, or reference
  `var(--accent-wash)`/`var(--accent-wash-strong)` once those exist.
- A handful of one-off blues outside `:root` that are page-specific gradients, not systemic:
  `#0077ff` (OAuth-style accents around lines 701-727), `#9abaff`/`#55482a` (line ~529-530,
  needs inspection in context — may be an unrelated gradient stop, verify before touching).

None of this needs a new abstraction (no new CSS architecture, no CSS-in-JS migration) — it's a
token-value edit plus a bounded list of hardcoded-hex touch-ups, all inside one file.

### Mobile (`apps/mobile/src/theme.ts`)

Already done (commit `a711429`, reproduced above for reference). No action. Future-proofing note:
the `symmetryZ: "#5b9cff"` entry is **intentionally** still blue — it's the Z-axis gizmo color
(X=red, Y=green, Z=blue is a universal 3D-software convention, not a brand color) and must stay
blue regardless of theme. Confirmed correct as-is; flagging so a future pass doesn't "fix" it by
mistake.

### Cream-green (deferred)

Do not build. To keep the architecture theme-able without a rewrite later: web already centralizes
everything through `:root` CSS custom properties, which is the correct foundation — a second theme
is just a second `:root`-equivalent value set behind a `data-theme` attribute or a settings-driven
class, swapped at runtime. Mobile's `theme.ts` is a single exported `colors` object; making it
theme-able later means wrapping it in a context/hook that picks between two palette objects — a
small, well-understood change, not an architecture rewrite. No action needed now beyond "don't add
anything that would make this harder" (e.g. don't hardcode more hex values outside the token
files).

### Logomark

Reference images show an orange hexagon outline containing a smaller circle/ring (a stylized "O"
or lens), next to the wordmark "Sova 3d" (regular weight "Sova", bold/accent-colored "3d" or vice
versa — treatment varies slightly across the reference slides).

Current state:
- Web: `.brand-mark` is a rounded-square `div` with a blue gradient background and a single
  Unicode glyph inside (not shown in the excerpt read, but structurally a flat icon box).
- Mobile (already shipped): `local.brandMark` in `Onboarding.tsx` is literally the single character
  `"⬡"` (U+2B21, white hexagon) rendered in `colors.accent`. Functional and on-brand in color, but
  not a crafted mark — it's relying on a font glyph, which renders inconsically across platforms
  (weight, stroke, inner-circle detail all vary by system font).

Recommendation: build a small inline SVG hexagon-plus-ring mark, consistent with how the existing
`auth-object` blob (`apps/web/src/app/login/page.tsx` + `.auth-object` rules in `globals.css`) is
pure CSS/markup rather than an image asset. A hexagon outline + inner circle is cheap to express as
an SVG `<polygon>` + `<circle>`, stroke-colored `var(--accent)`/`colors.accent`, sized to the
existing `.brand-mark`/`local.brandMark` box. This should replace the `"⬡"` glyph on mobile and the
gradient box on web, in one shared visual language. This is a small, self-contained increment-1
task (it's the one piece of "logomark" work not already covered by the mobile palette commit) —
not a new illustration system, just one reusable mark component per platform.

---

## 2. Default 3D-viewer model color: plan

**Mandate:** default/neutral model color = white. Orange in reference renders is that reference
product's demo material, not a SOVA default.

### Current state (already mostly correct — this is a smaller fix than the task brief assumed)

**Mobile** (`apps/mobile/src/ModelViewer.tsx`):
- Line 382: `current.material.color.set(coloured ? "#ffffff" : "#f3f1ec");` — uncolored geometry
  already renders a warm off-white (`#f3f1ec`), colored geometry renders pure white tinted by
  vertex colors. This is already correct per the mandate; no change needed.
- Line 802-803: the standalone preview/placeholder material also defaults to `"#f3f1ec"`. Correct.
- Lines 457-481, 817: selection outline, vertex points, and the viewport-accent line already use
  `colors.selection` (`#ff8a42`) / `colors.accent` (now orange) — these are UI overlay colors, not
  model material colors, so they're correctly orange (an orange selection highlight on a white
  model is exactly the reference pattern, e.g. image O1/O2's orange selection wireframe on the
  orange demo product — the *demo* product also happens to be orange in the references, which is
  coincidental to the brand color, not evidence that SOVA should tint models orange).

**Web** (`apps/web/src/components/ModelViewer.tsx`, `Body` component, lines ~276-282):
```js
const color = body.coloured
  ? "#ffffff"
  : selected
    ? "#5b9cff"   // <- blue, should become orange accent
    : hovered
      ? "#8fb8ff" // <- blue tint, should become orange tint
      : "#c9ced8"; // <- already a neutral light grey, not blue; could warm slightly to match mobile's #f3f1ec but isn't wrong
```
Plus two more hardcoded spots:
- Line 218: `color="#ffb020"` — this is an *already-orange* accent used somewhere in the viewer
  (likely a gizmo/highlight; worth confirming it's intentional and not a leftover test color — if
  it's a measurement or axis marker, leave it; if it's meant to be the themed accent, route it
  through the CSS var equivalent so future palette tweaks don't require another hunt-and-replace).
- Line 854: `color={index === 0 ? "#ffb020" : "#5b9cff"}` — two-tone marker/annotation coloring;
  the blue half should become the new accent orange, but check this doesn't make both halves the
  same orange and lose the visual distinction the two-tone was providing (may need accent vs. a
  neutral, not accent vs. accent-adjacent-orange).

**Scope guardrail (why this won't regress real material data):** `body.coloured` is the existing
gate — it's `true` only when the geometry carries vertex colors (i.e., a user has painted it, or
it came from a photo-texture/scan path that assigns real color data). The default/fallback color
only ever applies when `coloured` is `false`, i.e., genuinely no color data exists. So:
- Exterior/photo-texture scan path: unaffected, already gated by `coloured`.
- Paint/material-layers feature (§4 — exists on mobile as `MeshLayersSheet.tsx`, needs confirming
  on web): also unaffected as long as it sets `coloured`/vertex colors when a user assigns a layer
  color, which is the existing mechanism — just confirm during implementation that the layers
  feature writes through this same flag rather than a separate color path that might coincidentally
  default to blue or orange on its own.

**Action for increment 1:** on web, change `"#5b9cff"` → `var(--accent)` equivalent (likely
`"#ff6b1a"` or read from a shared constant so it doesn't drift from the CSS token) for the
`selected` state, and `"#8fb8ff"` → an orange tint for `hovered`. Leave `"#c9ced8"` (unselected
default) as-is or warm it slightly toward `#e8e5df`/`#f3f1ec` to match mobile's off-white — cosmetic
parity, not a correctness fix, since `#c9ced8` already satisfies "not orange, reads as neutral."
Audit lines 218 and 854 during implementation (not blind in this doc) to confirm intent before
touching them.

---

## 3. Onboarding redo

**Mobile: already done.** `apps/mobile/src/Onboarding.tsx` is the reference implementation —
three numbered steps (idea → edit → export) with a hero visual area (grid lines + "orange glow" +
a PNG product photo — note this uses a raster asset, `assets/onboarding/orange-maker-caddy.png`,
not a pure-vector illustration; flagged below), contextual overlay chips per step (measurement chip
on "edit," readiness chip on "export," model chip on "idea"), action rows with glyph icons in
accent-tinted circles, and format chips (STL/3MF/GLB) on the export step. Tablet gets a
side-by-side layout via `isTablet` instead of stacked.

One open item even on the finished mobile version: it uses one static product photo
(`orange-maker-caddy.png`) as the hero across all three slides. That's a real image asset, which
the owner's "real illustrative elements... not external image assets" guidance (and the earlier
avoid-generic-ai-ui feedback) leans against, though a single owned/shot product photo is different
from a stock AI-card icon — it's arguably fine as "real product imagery" per the file's own header
comment ("Sova's first-run story: real product imagery with native, accessible controls"). Decide
explicitly rather than silently porting: either keep the photo approach (and source/commission
equivalent photos for web, or reuse the same asset), or replace with the vector/shape-based
`auth-object`-style illustration the brief asked for. Recommend asking the owner only if web and
mobile should look identical here — otherwise default to reusing the mobile pattern for
consistency, since it already shipped and the owner hasn't objected to it in review.

**Web: needs the full redo**, porting the mobile structure:

Current `apps/web/src/components/Onboarding.tsx` (61 lines): three slides, each a single Unicode
glyph (`✦`, `⌂`, `⬡`) in a `.onboarding-icon` circle (currently blue-tinted per globals.css line
1972), a title, a note, dot pagination, and a Skip/Next/Get-started button. Content copy ("Create
3D from words, photos and scans" / "Scan rooms and buildings" / "Edit with precision") differs from
mobile's current three slides ("От идеи к модели" / "Меняйте точно" / "Подготовьте к печати") —
these are two different slide sets describing different capability groupings (web's covers
creation-input + room-scanning + precision-editing; mobile's covers idea→edit→export as a single
workflow arc). Decide whether web should adopt mobile's workflow-arc framing (recommended, since
it matches the reference mockups' D1/D3/O-series narrative and is the more recently
owner-reviewed version) or keep its current three-capability framing re-themed in place (cheaper,
less consistent with mobile).

Recommended concrete plan for web, mirroring mobile's structure:
1. Replace the three `SLIDES` entries with the mobile three-step arc (reuse mobile's RU/EN copy
   verbatim for consistency, or keep web's existing broader capability-survey copy — pick one; see
   above).
2. Replace `.onboarding-icon`'s single-glyph circle with the new hexagon-mark component (§1) sized
   up, or a simple SVG hero matching mobile's "grid + glow + accent chip" treatment — CSS-only
   (border grid lines, a radial-gradient blob for the "glow," one small floating chip with
   step-specific micro-copy), no new image assets required for parity with mobile's non-photo
   elements (grid/glow/chips are already pure CSS there).
3. Re-theme `.onboarding-dots`, `.onboarding-skip`, `.onboarding-next` via the token swap in §1 —
   no bespoke work needed beyond what the global `--accent` swap already does, since these classes
   already reference `var(--accent)`.
4. Add the export-step format chips (STL/3MF/GLB) that mobile's version has and web's doesn't —
   small, self-contained addition, reuses whatever format-chip markup already exists elsewhere in
   `globals.css` (`.export-format`, already themed via `var(--accent)`).

This is scoped as a single-file-plus-CSS change, no new dependencies.

---

## 4. Prioritized gap-check

Cross-referencing the dark-orange reference set (O1-O5, O10, D1, D3) against the current SOVA
codebase. Owner's framing: "all of it should be ours, but peek here for anything we're missing" —
treat this as a completeness check, not a clone target.

| Reference capability | Status | Evidence |
|---|---|---|
| Left icon-rail nav (Проекты/Создать/Сканер/Маркет/Профиль) | **Exists** | `apps/mobile/src/WorkspaceShell.tsx`; web has an equivalent top/side nav in `TopBar.tsx` + `globals.css` `.topbar-links` |
| 3D viewport with axis-cube gizmo | **Exists** | Both `ModelViewer.tsx` files render a gizmo; mobile's grid/axis overlay confirmed in `WorkspaceShell.tsx` |
| 2D/3D view toggle | **Exists** | `apps/mobile/src/WorkspaceShell.tsx`, `apps/mobile/app/project/[id].tsx`, `apps/mobile/src/ModelViewer.tsx` all reference a 2D/3D mode; confirm web parity during implementation (not explicitly greped on web, worth a quick check before assuming a gap) |
| Selection/Transform panel (Position/Size/Rotation, mm) | **Exists** | `MeshEditPanel.tsx`, `ExactCadPanel.tsx` on web; mobile's edit-mode sheets per `EditModeSheet.tsx` |
| Boolean operations (union/subtract/intersect) | **Exists** | `apps/mobile/src/capabilities.ts` declares boolean-op capability; `OperationStackPanel.tsx`/`MeshModifierStackPanel.tsx` on web are the likely home — verify exact UI parity (icon-button row vs. menu) during implementation, but the *capability* is not missing |
| Paint/Material panel with named, reorderable layers list | **Exists** | `apps/mobile/src/MeshLayersSheet.tsx` — confirm a web equivalent exists (not directly found in the component list scanned; `ExactCadPanel.tsx`/`MeshEditPanel.tsx` may cover it, or it may be mobile-only today — **this one needs a direct implementation-time check, flagged as the most likely genuine partial-gap** on web) |
| Versions panel with thumbnails, timestamps, current highlighted | **Exists** | `ExactCadPanel.tsx`, `apps/web/src/app/projects/[id]/page.tsx` (`activeVersion` logic seen directly, line ~4015) |
| Print-readiness checklist (Проверка: Герметичность/Толщина стенок/...) | **Exists** | `MeshEditPanel.tsx`, `apps/web/src/app/slicer/page.tsx`, `apps/web/src/app/modeling/page.tsx`, `apps/web/src/app/scanner/[id]/page.tsx` all reference print-check concepts; mobile's `EditModeSheet.tsx`/`WorkspaceShell.tsx` too. Exact per-row breakdown (Герметичность/Толщина стенок/Нависающие элементы/Пересечения/Размеры individually) not verified line-by-line — likely present in some form given the breadth of hits, worth a quick visual confirm rather than assuming full parity |
| Export panel (STL/3MF/OBJ/GLB chips) | **Exists** | Format-related hits across `apps/web/src/app/page.tsx`, `convert/page.tsx`, `projects/[id]/page.tsx`, `proGate.ts`; mobile onboarding's own format chips mirror it |
| Extrude-style operation panel (Расстояние/Направление/Объединить с телом) | **Likely exists, not confirmed** | `OperationStackPanel.tsx`/`MeshModifierStackPanel.tsx` are the obvious home for a modifier-stack-style extrude editor given their names, but the specific field set (distance/direction/merge-with-body toggle) wasn't read line-by-line — check before scoping as new work |
| Bottom persistent AI command bar ("Опишите изменение...") | **Exists** | `apps/mobile/app/project/[id].tsx` matched directly on the literal Russian placeholder string |
| Hexagon "Sova 3d" logomark | **Partial** | Color is now right on mobile (orange `"⬡"` glyph); neither platform has a crafted vector mark yet — see §1 |

**Bottom line:** nothing in the reference set is a genuinely new feature. Every distinctive
capability shown already exists in SOVA in some form. The one item worth a dedicated
implementation-time check (not a doc-time guess) is whether web has a layered paint/material list
equivalent to mobile's `MeshLayersSheet.tsx` — everything else is "exists, confirm exact field
parity" at worst. This confirms the rebrand is almost entirely a **re-theme**, not a feature build.

---

## 5. Staged rollout plan

### Increment 1 (propose for immediate pickup — small, bounded, high-visibility)

1. Web token swap: `apps/web/src/app/globals.css` `:root` values (§1) + the enumerated list of
   hardcoded-blue touch-up sites (brand-mark, topbar-create, topbar-avatar, the ~9 raw-rgba glow
   sites, the `.onboarding-icon` background).
2. Web `ModelViewer.tsx` accent swap for `selected`/`hovered` states (§2), plus an intent-check on
   the two hardcoded `#ffb020`/`#5b9cff` sites at lines 218 and 854.
3. Web `Onboarding.tsx` redo to match the mobile pattern (§3) — copy-framing decision needed first
   (reuse mobile's three-step arc vs. keep web's current three-capability framing), then the
   markup/CSS work.
4. New shared hexagon-mark SVG component, web + mobile (§1) — the one piece of logomark work not
   already covered by the existing mobile palette commit.
5. Confirm (don't yet build) the one flagged gap-check uncertainty: does web have a layered
   material/color-assignment panel. If missing, that's explicitly **out of scope for increment 1**
   — note it for increment 2 as a possible small net-new feature rather than a re-theme item.

Everything else — `apps/mobile/src/theme.ts`, `WorkspaceShell.tsx`, the current mobile
`Onboarding.tsx`, `sign-in.tsx` — is **already shipped** and needs no increment-1 work; it's listed
here only so a future reader doesn't re-do it.

### Increment 2 (later — full web Studio panel re-theme)

Mechanically, most of this is already handled by the root-token swap in increment 1, since the
majority of `globals.css` selectors already route through `var(--accent)`. What remains is a
systematic visual QA pass across every panel to catch any remaining hardcoded hex values the greps
in this doc didn't surface (the doc's searches were targeted, not exhaustive), plus the few panels
flagged above as needing exact-parity confirmation against the reference set. Enumerate the web
component surface for that QA pass:

`CreateHub.tsx`, `EnclosureCard.tsx`, `EngineerCard.tsx`, `ExactCadPanel.tsx`,
`FeedbackButtons.tsx`, `FitTestCard.tsx`, `FragmentsViewer.tsx`, `HouseBoxWizard.tsx`,
`HouseWallsWizard.tsx`, `Inspector.tsx`, `LicenceCard.tsx`, `ListingCard.tsx`,
`LoadingScreen.tsx`, `MeshEditPanel.tsx`, `MeshModifierStackPanel.tsx`, `ModellingPanel.tsx`,
`OperationStackPanel.tsx`, `PartsCard.tsx`, `PlanEditor.tsx`, `ProLock.tsx`,
`ProvenanceGraph.tsx`, `PublishCard.tsx`, `RegionOverlay.tsx`, `SceneTreePanel.tsx`,
`SplitCard.tsx`, `TemplateGallery.tsx`, `TopBar.tsx`, `TopologyOverlay.tsx`,
`TrainingConsentCard.tsx`, `VoiceButton.tsx`, `WallDrawingCanvas.tsx`, plus the page-level
files (`app/slicer/page.tsx`, `app/modeling/page.tsx`, `app/scanner/[id]/page.tsx`,
`app/projects/[id]/page.tsx`, `app/convert/page.tsx`, `app/page.tsx`).

Also increment-2 scope: the possible net-new layered-materials panel on web (if increment 1's
confirmation step finds it's actually missing), the cream-green theme architecture (settings toggle
+ second palette, still not drawn, just wired), and any exact-field-parity gaps flagged as "likely
exists, not confirmed" in §4's table once someone actually opens those panels in a running app.

### Not in scope anywhere in this doc

The split-workspace / reference-photo 2D+3D pane idea mentioned alongside the rebrand in the same
owner conversation is explicitly a separate, undecided feature — already tracked in
`docs/design/split-workspace-feature-recommendation.md` and `docs/design/LINKED-2D-3D-REFERENCE-WORKSPACE.md`.
Not part of this rebrand's scope.
