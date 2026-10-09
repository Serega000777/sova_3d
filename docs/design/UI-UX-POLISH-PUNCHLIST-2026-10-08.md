# UI/UX polish punch list — 2026-10-08

Scope: a close inspection of real UI code across all three client surfaces (`apps/web`
Studio/market/settings/auth, `apps/desktop`'s Tauri shell, `apps/mobile` phone+tablet) looking
for polish-level defects — visual inconsistency, confusing interaction, missing affordance,
inconsistent terminology, information-density problems, weak empty/error/loading states,
accessibility gaps — **inside** features that are already shipped. This is not a feature audit.

**Explicitly excluded** (already tracked elsewhere, not re-reported here):
- Anything listed as "Отсутствует"/"Частично" in `docs/COMPETITOR_UI_ANALYSIS.md` (e.g. missing
  scan-result action column, missing "Исследовать" feeds-by-type screen, missing thumbnails in
  the library, gaussian splats, multi-room StructureBuilder, etc.) — those are feature gaps, not
  polish issues in shipped work.
- The four UX recommendations from `docs/COMPETITOR_BRIEF_HUNYUAN_NOMAD_2026-10-08.md` Part 3(a)
  already applied per `docs/IMPLEMENTED.md` (gesture-first mobile mesh-edit panels, "Layers"
  vocabulary for the modifier stack, multi-photo attachment with per-photo thumbnails, multi-view
  capture nudge — commits `935d761`, `f168d9c`, `bf1e74c`).
- The tablet-specific CAD-panel layout, which is a parallel design task
  (`docs/design/MOBILE-CAD-PANELS-tablet-layout.md` did not exist at the time of this audit).
  Findings below about tablet are scoped to *everything else* on tablet.
- Anything logged as a known limitation in `docs/IN_PROGRESS.md` (physical LiDAR unverified,
  gaussian splats `not_supported_yet`, multi-room merge, etc.).

Each finding below names the exact file/line, the concrete defect, and a one-line fix direction.
Within each section, findings are ordered highest-impact/lowest-effort first; anything that would
require a structural redesign is flagged **out of scope for a polish pass** rather than listed as
a quick win.

**Visual-treatment constraint (owner note):** the product explicitly does not want the generic
"AI-generated UI" look — flat colored-background square/rounded card containers scattered across
a page. Where a finding below touches visual treatment (not just copy/translation), the fix
direction points at a *specific* existing, more-considered pattern already in this codebase —
e.g. the split-panel `auth-shell`/`auth-story` with its orbit illustration in
`apps/web/src/app/login/page.tsx:57-70` — or at specific patterns from the competitor research in
`docs/COMPETITOR_UI_ANALYSIS.md` / `docs/COMPETITOR_BRIEF_HUNYUAN_NOMAD_2026-10-08.md`, rather than
a generic "wrap it in a card" instruction. Most findings in this pass are pure i18n/plumbing fixes
with no visual-treatment decision attached; T1/T2 below are the ones where this matters.

---

## Web / Desktop

`apps/desktop` is a thin Tauri shell around the same Next.js app in `apps/web` — every fix below
under "web" also fixes desktop automatically. One item (W7) is Tauri-shell-specific.

| # | Impact/Effort | Finding | Fix direction |
|---|---|---|---|
| W1 | **High / Low** | `apps/web/src/app/settings/page.tsx` lets the user pick a UI language at line 86-90 ("Язык ответов ИИ и подписей" → Русский/English, saved via `updateMe({ locale })`), but the Settings page itself never reads that choice back for its own chrome — every label on the page ("Настройки" 77, "Профиль" 80, "Сохранить"/"Сохраняем…" 95, "Тариф" 103, "Способы входа" 127, "Рабочие пространства" 143, "Принтеры и материалы" 155, "Сеанс" 163, "Выйти на этом устройстве" 174) is hardcoded Russian. Worse, the Free/Pro feature lists at lines 110 and 116 render `TIER_FEATURES.free.ru.map(...)` / `TIER_FEATURES.pro.ru.map(...)` — literally hardcoded to `.ru` regardless of the `locale` state variable sitting right above them. | Swap `.ru` for `[locale]` on lines 110/116 (one-line fix); thread the existing `language`/`t()` pattern used elsewhere in the Studio into this page's own labels. |
| W2 | **High / Low** | `apps/web/src/components/TopBar.tsx` — the persistent navigation rendered on *every* page via `apps/web/src/app/layout.tsx:17` — hardcodes all Russian text with no `language` prop at all: nav labels (lines 10-16: "Моделлинг"/"Проекты"/"Конвертация"/"Слайсер"/"Маркетплейс"/"3D-сканер"/"Планы"), profile fallback "Профиль" (34), aria-labels (38, 43), menu items "Настройки"/"Выйти" (58-59, 78-79), "Новый проект" (67), "Войти" (83). Every other major panel in the Studio tree (`ExactCadPanel`, `CreateHub`, `SceneTreePanel`, `OperationStackPanel`, `MeshModifierStackPanel`, `Onboarding`, `HouseBoxWizard`/`HouseWallsWizard`, `WallDrawingCanvas`) accepts a `language: "en"\|"ru"` prop and branches on it — TopBar is the one piece of chrome visible everywhere that doesn't. | Accept `language` in `TopBar` (derive the same way the Studio page does, `apps/web/src/app/projects/[id]/page.tsx:233-236`) and route labels through a `T[language]` table like `EnclosureCard` uses. |
| W3 | **Medium / Medium** | `apps/web/src/app/market/page.tsx` and `apps/web/src/app/creators/[handle]/page.tsx` are 100% hardcoded English with zero `language`/`t()` infrastructure — the only major screens in the web app with no Russian at all: "Marketplace" (96), tab labels "everything"/"creators I follow"/"my listings" (104), placeholder "cable clip, phone stand, bracket…" (114), "free only" (130), sort options "newest"/"most taken"/"cheapest" (124-126), empty states (155-161: "Follow a creator and their new listings show up here.", "Nothing on the shelf matches..."), "Your creator profile"/"Save profile" (166-196). This is inconsistent with the Russian-primary rest of the site, including the equivalent library/create flow in Studio. | Give Market/Creators the same bilingual table pattern already used by `EnclosureCard`/`CreateHub`, defaulting to Russian like every other default-locale screen. |
| W4 | **Low / Low** | `apps/web/src/components/EngineerCard.tsx` has no `language` prop at all (fully Russian-hardcoded — the inverse of its mobile counterpart, which is fully English, see M10). Line 151's placeholder literally mixes two languages mid-string: `placeholder="What is it for? (держатель для шланга на улице)"`. | Translate the placeholder fully to Russian to match the rest of the card (or add the same bilingual table used elsewhere if English support is wanted here too). |
| W5 | **Low / Low** | `apps/web/src/components/ExactCadPanel.tsx` NURBS sketch-segment and NURBS-surface subsections drop the `ru ?` ternary pattern every neighboring field in the *same panel* uses: `Degree`/`Weights`/`Knots`/`Multiplicities` (551-554), bare `Weights` (577), `U degree`/`V degree`/`U knots`/`V knots`/`U multiplicities`/`V multiplicities` (581-586) all render English-only — while the field directly below them, `{ru ? "Толщина, мм" : "Thickness, mm"}` (587), correctly branches. | Extend the existing ternary to these ~10 labels; the correct pattern is already in the same file two lines away. |
| W6 | **High / Medium** | Every top-level web route returns a bare `null` while `!ready` (confirmed in 14 files: `projects/[id]/page.tsx`, `market/page.tsx`, `settings/page.tsx`, `slicer/page.tsx`, `scanner/page.tsx`, `scanner/[id]/page.tsx`, `convert/page.tsx`, `creators/[handle]/page.tsx`, `printers/page.tsx`, `market/[id]/page.tsx`, `new/page.tsx`, `modeling/page.tsx`, `page.tsx`, `projects/[id]/takeoff/page.tsx`). There is no shared skeleton/spinner component anywhere in `apps/web/src/components` — every navigation and every refresh flashes to a blank page before content appears. | Introduce one shared `<LoadingScreen/>` (even a simple centered spinner matching `globals.css` tokens) and swap it in for the `return null` branch across these files. |
| W7 | **Low / Low**, Tauri-specific | `apps/desktop/launcher/index.html` — the raw HTML screen Tauri shows before the embedded web app loads (first run, or when the saved workspace URL fails) — is a separate hand-rolled page: fully English ("Open the workspace this machine should talk to...", "Open workspace", "Use localhost"), titled "Physical AI 3D" (line 6, 68) rather than the "SOVA" branding used on the actual login screen (`apps/web/src/app/login/page.tsx:59`: "SOVA · PHYSICAL AI"), and duplicates the web app's color tokens inline (lines 8-19) instead of sharing `globals.css`. It visibly reads as a different, less-finished product bolted onto the front of the real app. | Rebrand title/copy to SOVA, localize to Russian to match the shell it leads into, point inline tokens at the same palette (or inline the shared CSS vars). |

**Out of scope for a polish pass:** nothing found here needs a structural redesign — all seven
items are localized, surgical fixes.

---

## Mobile

| # | Impact/Effort | Finding | Fix direction |
|---|---|---|---|
| M1 | **High / Low** | `apps/mobile/app/project/[id].tsx` lines 767-814 — the main mode toolbar — mixes English and Russian in the same row: "Outline an area"/"Outlining…" (777), "Paint"/"Painting…" (788), "Edit mesh"/"Editing mesh…" (799), "Grid" (806), "Layers" (813), while a modal directly above it (lines 742, 761: "Что здесь исправить?" / "Исправить") and the rest of the screen are Russian. This is the single most visible language inconsistency in the app — one toolbar, two languages, no reason for the split. | Translate the five button labels (and their progress-state variants) to Russian to match the rest of the screen. |
| M2 | **High / Low** | The three newly-shipped mesh-edit sheets — `apps/mobile/src/EditModeSheet.tsx`, `GridPanel.tsx`, `MeshLayersSheet.tsx` — are 100% English end to end (headings "Edit mesh"/"Grid & symmetry"/"Layers", operation buttons "Move"/"Extrude"/"Inset"/"Bevel"/"Delete", all helper copy), breaking from the Russian-primary app the moment mesh editing opens. `MeshLayersSheet.tsx` lines 9-16 even built a correct `{ ru, en }` `LABELS` table, then line 147 only ever reads `.en` (`LABELS[entry.type]?.en ?? entry.type`) — the Russian half is dead code. | One-line fix for the dead `ru` field (read the right key based on an actual locale signal); translate the rest of the three sheets' static copy to match M1's fix. |
| M3 | **Medium / Low** | `apps/mobile/src/EngineerCard.tsx` is fully English ("Ask the engineer" 103, "What is it for?" 118, "Apply: {label}" 67, "The engineer also noticed:" 181), and its own `EXAMPLES` array (lines 11-16) mixes languages within one list: `"Эта стенка слишком тонкая?"`, `"Will it hold 5 kg?"`, `"Какой пластик выбрать для улицы?"`, `"Holes for M5 screws"` — a user tapping a suggested-question chip gets a random language. | Translate the whole card to Russian (matching the rest of the project screen it's embedded in) and make the `EXAMPLES` list single-language. |
| M4 | **Medium / Low** | `apps/mobile/src/VoiceButton.tsx` line 90: `{listening ? "● Listening…" : "🎤 Speak"}` is hardcoded English even though the component already receives a `language: "ru"\|"en"` prop (line 38) — currently used only to pick the speech-recognition locale (line 59), not the button's own label. | Branch the button text on the existing `language` prop — the plumbing is already there. |
| M5 | **Medium / Low** | Every async action in the main editor surfaces its busy/progress state as a literal English string passed straight to `track()` and rendered verbatim via `{busy && <Text>{busy}</Text>}` (`apps/mobile/app/project/[id].tsx` lines 880, 979): `"Planning & building"` (357), `"Painting"` (425), `"Editing mesh"` (481), `"Rebuilding mesh layers"` (500), `"Resizing"` (546), `"Measuring"` (583), `"Applying the fix"` (604) — plus English fallback error strings shown the same way: `"the command failed"` (369), `"the paint did not land"` (427), `"the mesh edit failed"` (486), `"the layers did not rebuild"` (502), `"the edit failed"` (548), `"the engineer could not answer"` (585), `"the fix failed"` (606) — directly beside Russian error text elsewhere on the same screen (e.g. `"Размер — от 5 до 1000 мм"`, line 384). | Translate the ~15 `track()` labels and fallback error strings to Russian in one pass — every call site is already centralized through `track()`. |
| M6 | **Low / Low** | The signed-out gate on the library screen (`apps/mobile/app/index.tsx` lines 144-157: "Physical AI 3D", "Describe an object, get a model you can edit and print. Sign in to start.", "Sign in") is entirely English, but tapping "Sign in" lands on `apps/mobile/app/sign-in.tsx`, titled "Вход" (line 142) in Russian — the language switches mid-flow on a new user's very first screen. | Translate the gate copy to Russian to match the screen it leads into. |
| M7 | **Low / Low** | On the same library screen, the "Marketplace" card (`index.tsx` lines 229-241: heading "Marketplace", "Models other makers put on the shelf.", "Get"/"Buy" buttons) and the "Sign out" button (316) are English, sitting directly between Russian section headings ("Начните с шаблона" 208, "3D-сканер" 258, "Библиотека" 268). | Translate these four strings to match the surrounding Russian sections. |

**Out of scope for a polish pass:** none of the above require redesign — all are translation/
plumbing fixes to features that already work correctly.

---

## Mobile tablet-specific

(Excludes the CAD-panel tablet layout being designed separately.)

| # | Impact/Effort | Finding | Fix direction |
|---|---|---|---|
| T1 | **High / Medium** | No tablet-width-responsive logic exists anywhere in the mobile codebase — confirmed by grepping `apps/mobile/src` and `apps/mobile/app` for `useWindowDimensions`, `Dimensions.get`, and `isTablet`: zero matches in any file. This is broader than the in-flight CAD-panel work: the library screen's project list (`apps/mobile/app/index.tsx` lines 297-306) stays a single-column `ScrollView` at any width, leaving roughly half an iPad screen as unused margin instead of a 2-3 column grid; every bottom sheet (`CreateSheet.tsx`, `EditModeSheet.tsx`, `GridPanel.tsx`, `MeshLayersSheet.tsx`) is a full-bleed-width modal (e.g. `GridPanel.tsx` lines 27-35 size it to the full window width with no max-width clamp) that will stretch edge-to-edge on a tablet rather than using a narrower, centered sheet. | Needs its own small ticket, since it's app-wide and not limited to the CAD panels: add a shared `useIsTablet()`/breakpoint helper, apply a `maxWidth` clamp to bottom sheets, and give the library list a tablet-width treatment above a width threshold. **Caution:** the project list currently renders each item as a full-width flat `styles.card`/`colors.panel2` row (`index.tsx:303`); don't just re-tile that same flat-card row into a denser 2-3 column grid at tablet width — multiplying flat colored-card tiles across a wider screen is exactly the generic AI-UI look the product is avoiding. Use thumbnail-led tiles once library thumbnails ship (tracked as a feature gap in `docs/COMPETITOR_UI_ANALYSIS.md`), or take a cue from the considered split-panel treatment in `apps/web/src/app/login/page.tsx`'s `auth-shell` (illustration/content pairing rather than a card grid) before defaulting to more cards. |
| T2 | **Low / Low** | `apps/mobile/src/CreateSheet.tsx`'s scenario grid and guide stepper (lines 68-101) lay out as a single vertical list regardless of width — same root cause as T1, called out separately because it's the first screen a new tablet user sees when starting a project, so the wasted horizontal space is especially visible at the first-impression moment. | Covered by the same fix as T1 once a tablet breakpoint exists. **Caution:** each scenario here is already a flat `styles.card` row with an icon chip (`CreateSheet.tsx:82-96`); at tablet width, avoid simply repeating that same flat-card unit in a multi-column grid (the generic-card-grid look called out in T1) — group by `SCENARIO_GROUPS` with clearer visual hierarchy (section framing, icon/illustration emphasis) instead of just adding columns of identical small cards. |

---

## Top 8-10 cross-surface shortlist — hand to implementation first

Ranked by genuine impact-vs-effort across all three surfaces, not reading order:

1. **M1** — Mobile main-editor toolbar mixes English/Russian in one row (`project/[id].tsx:767-814`). Highest-visibility single bug, five-label translation fix.
2. **W1** — Web Settings page's language switcher doesn't switch itself, and ignores its own `locale` for the Free/Pro feature list (`settings/page.tsx:110,116`). The literal "language switcher is broken" bug — two-line fix for the worst part, page-wide for full consistency.
3. **M2** — Mobile's three new mesh-edit sheets are all-English, including a one-line dead-code bug (`MeshLayersSheet.tsx:147` reads `.en` from a table that has `.ru` sitting right next to it, unused).
4. **W2** — Web `TopBar` hardcodes Russian with no `language` prop at all, unlike nearly every sibling component — blocks #2 from ever being end-to-end, since nav never follows locale regardless of what Settings fixes.
5. **M5** — Every busy/progress label and error fallback in the mobile editor is English, shown next to Russian error text on the same screen — systemic, but centralized through one `track()` call site, so one targeted pass fixes ~15 occurrences at once.
6. **W3** — Web Market + Creators pages are 100% English with zero i18n hook — same root cause and fix pattern as #2/#4, just on web.
7. **M3** — Mobile `EngineerCard`'s own example-question list mixes Russian and English within a single array — small, visible, and the kind of thing that looks bad in any product demo.
8. **W6** — All 14 top-level web pages return a blank screen while loading, no shared skeleton anywhere in the app — cross-cutting, moderate effort, but visible on every single navigation.
9. **T1** — Zero tablet-width-responsive logic anywhere in mobile, confirmed by grep — scoped explicitly as adjacent to (not a duplicate of) the parallel CAD-panel tablet task, needs its own ticket since it covers the library screen and every bottom sheet.
10. **W5** — Web `ExactCadPanel` NURBS fields missing the `ru` ternary every sibling field already has — the cheapest fix in the entire list (extend an existing pattern two lines away), worth bundling with #2/#4/#6 as one "finish the `language` prop rollout" pass.
