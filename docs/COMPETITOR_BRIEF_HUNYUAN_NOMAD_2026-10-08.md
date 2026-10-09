# Competitor brief: Tencent Hunyuan 3D & Nomad Sculpt — implications for SOVA

2026-10-08. Research brief, self-contained (does not depend on prior chat turns). Covers Tencent
Hunyuan 3D (generation engine + desktop Studio), Nomad Sculpt (mobile-first sculpting app), and a
concrete "so what for SOVA" mapping against the current feature registry
(`docs/v2/v1_core/FEATURE_REGISTRY.txt`, `docs/FEATURE_REGISTRY_ADDENDUM.md`,
`docs/COMPETITOR_UI_ANALYSIS.md`).

---

## Part 1 — Tencent Hunyuan 3D

### 1.1 Model lineage and architecture

Tencent's Hunyuan 3D generative line has moved through four public generations:

- **Hunyuan3D-2.1** (June 2025, open-sourced, weights on Hugging Face). Documented two-stage
  architecture: **Hunyuan3D-Shape-2.1**, a 3.3B-parameter flow-matching diffusion transformer that
  turns an image into geometry, plus **Hunyuan3D-Paint-2.1**, a 2B-parameter PBR texture-synthesis
  model producing physically grounded materials (metallic reflection, subsurface scattering).
  Conditioning is multi-view (6 views by default). VRAM needs: ~10 GB for shape-only, ~21 GB for
  texture-only, ~29 GB for the combined pipeline. Technical report: arXiv:2506.15442. Weights:
  huggingface.co/tencent/Hunyuan3D-2.1. ([Hunyuan3D on comfyui-wiki](https://comfyui-wiki.com/en/models/hunyuan3d))
- **Hunyuan3D 3.0** (September 2025): a 10B-parameter step up, Tencent states roughly 3x precision
  improvement over 2.x, geometric resolution up to 1536³ (3.6 billion effective voxels), and better
  facial/figure detail. ([stdaily.com coverage of Hunyuan 3D Studio](https://www.stdaily.com/web/gdxw/2025-09/25/content_407381.html))
- **Hunyuan3D 3.1** (current flagship as of this research; the owner's mobile screenshots label it
  "3D-поколение V3.1"). Pairs with **PartGen 1.5** (component-level decomposition with
  brush-driven refinement) and **PolyGen 1.5** (retopology, see below). The latest Studio build
  (1.2, in public beta) accepts up to eight multi-view input images per generation, improving color
  accuracy and detail density. ([ai-bot.cn Hunyuan 3D Studio overview](https://ai-bot.cn/hunyuan3d-studio/))

License for the 2.x open weights: the **"Tencent Hunyuan 3D Community License"** — free including
commercial use, until the licensee's product crosses 1M monthly active users, after which separate
negotiation with Tencent is required; the license also bans using Hunyuan3D outputs to train
competing 3D generative models. (Terms as stated on the Hugging Face model card,
huggingface.co/tencent/Hunyuan3D-2.1; treat as directional — verify current license text before
any product decision that depends on it.)

### 1.2 The known mesh-quality defect, and the 3.1 fix

Hunyuan3D 2.x's documented failure mode: output is "triangle soup" — frequently
**non-manifold** (bad edge connectivity, ambiguous face orientation, open boundaries,
self-intersecting faces). This is the exact defect class SOVA's own AI-repair feature
(`FEATURE_REGISTRY.txt` → "AI Repair: manifold, self-intersections, holes, inverted normals,
degenerate faces, thin walls") targets.

3.1's answer is **Hunyuan3D-PolyGen 1.5**, an autoregressive retopology model (not classical
decimation) that converts a dense/point-cloud-like mesh into quad-dominant topology with
continuous edge loops, using "Blocked and Patchified Tokenization" (BPT) to compress detail before
regenerating topology end-to-end. It ships three reduction presets (high/medium/low) and outputs
either quads or triangles depending on soft-surface vs. hard-surface needs; it is a standalone
service that will retopologize a GLB/OBJ from any source, not only Hunyuan's own output.
([Hunyuan Polygen 1.5 — The Essentials, help.scenario.com](https://help.scenario.com/articles/5113903414-hunyuan-polygen-1-5-the-essentials);
[scenario.com model page](https://www.scenario.com/models/hunyuan-polygen-15))

Third-party aggregator sources (not Tencent's own spec sheet) claim for 3.1 output: watertight
meshes, "zero holes/non-manifold edges," quad-dominant topology, 4K PBR maps (metallic/normal/
roughness), 40K–1.5M configurable polygon budgets, export to GLB/OBJ/FBX/STL/USDZ/PLY, and
generation times of 2–3 min (Rapid tier) or 3–6 min (Pro tier). **Treat these numbers as directional
marketing claims, not contractual specs** — they were not corroborated against a primary Tencent
source in this research pass.

### 1.3 Generation modes (Studio-wide, both mobile-web and desktop)

Confirmed across multiple sources — Tencent's own announcement, Chinese-language coverage, and
the comfyui-wiki release notes:

1. **Text-to-3D** — natural-language prompt (English or Chinese), style/material keywords, up to
   four candidate meshes per request.
2. **Image-to-3D** — single image or up to four/eight multi-view images (the limit has risen with
   each Studio version: 4 views at 2.0-era, 8 views at Studio 1.2 with the 3.1 base model).
3. **Sketch-to-3D** — black-and-white line sketch plus text attributes (color, category, material)
   fleshes the sketch into a textured mesh.
4. **Portrait-to-3D** — a photo of a person/face generates a 3D character model directly. Confirmed
   in Chinese-language coverage (ai-bot.cn, comfyui-wiki) but not mentioned on Tencent's own
   English-language global announcement page — likely a China-region-first feature not yet surfaced
   internationally, which matches the owner's observation that the mobile-web wrapper lags the
   mainland product.
5. **Smart/automatic topology** — not a separate input mode but a pipeline stage: automatic mesh
   optimization offering both triangle and quad output.

This confirms and completes the list the prior research pass left truncated: **text, image, sketch,
and portrait are all real, documented entry points**, not just the three visible in the owner's
mobile screenshots.
([Tencent global announcement](https://www.tencent.com/en-us/articles/2202235.html);
[comfyui-wiki 2025-01-24 release notes](https://comfyui-wiki.com/zh/news/2025-01-24-tencent-hunyuan3d-2-release);
[ai-bot.cn Studio overview](https://ai-bot.cn/hunyuan3d-studio/))

### 1.4 Desktop Studio: the full production pipeline

The desktop Studio (3d.hunyuan.tencent.com) is explicitly positioned as covering the whole
asset pipeline "from concept design to animation production," not just single-shot generation:

- **Concept & geometry**: text-to-image and image-to-multiview generation with style presets, feeding
  the shape model.
- **Topology**: automatic low-poly optimization with adjustable polygon counts (PolyGen 1.5).
- **UV mapping**: AI-driven UV unwrapping aligned to standard art pipeline conventions.
- **Texturing**: text- or image-driven PBR material generation (diffuse/metallic/roughness/normal).
- **Rigging & skinning**: automated skeleton setup for both humanoid and non-humanoid models, with
  built-in animation presets — humanoid and animal models can generate an animation preview
  directly from the rig.
- **Component editing**: PartGen 1.5 — intelligent decomposition of a model into parts with
  brush-based interactive refinement of individual components.

Target sectors named by Tencent: game development, animation production, industrial design, VFX,
and education/training. The platform reports 150+ enterprise adopters in mainland China and 2.6M+
community downloads of the open weights. Studio 1.2 is explicitly in **open public beta**
(application required). Map/level-creation workflows are stated as a future expansion, not yet
shipped.
([stdaily.com — Tencent professional AI 3D workbench](https://www.stdaily.com/web/gdxw/2025-09/25/content_407381.html);
[ai-bot.cn Hunyuan 3D Studio](https://ai-bot.cn/hunyuan3d-studio/))

No primary source in this research pass documented scene/gallery browsing UI, version history UX,
or a specific post-processing toolset beyond what's listed above — these likely exist inside the
authenticated Studio but weren't captured in public write-ups. Likewise no screenshots-level detail
was found beyond what the owner already captured from the mobile-web client.

### 1.5 Export formats and engine integration

OBJ and GLB are the documented baseline export formats, explicitly integrated with Unity, Unreal
Engine, and Blender. The broader third-party-sourced claim of GLB/OBJ/FBX/STL/USDZ/PLY export
(§1.2) was not independently corroborated on Tencent's own page — the primary source commits only
to OBJ/GLB plus engine interop.
([Tencent global announcement](https://www.tencent.com/en-us/articles/2202235.html))

### 1.6 Pricing / API tiers

- **Free / consumer tier**: 20 free generations per day on the standard web/mobile product.
- **Enterprise API (Tencent Cloud, "Hunyuan 3D Global")**: 200 free credits on sign-up, 1-year
  validity, then **$0.02 USD per credit**, daily settlement billing.
- **Per-generation API pricing** observed via reseller/aggregator platforms (not Tencent's own
  listed rate card, so treat as indicative): roughly $0.015 per model for the cheapest
  multi-view-turbo tier, up to $0.225–$0.375 per model for Rapid/Pro text-to-3D and image-to-3D.
  ([costgoat.com Hunyuan 3D pricing aggregation](https://costgoat.com/pricing/hunyuan-3d);
  [Tencent Cloud documentation](https://www.tencentcloud.com/document/product/1284/75281))

### 1.7 What this means for the owner's screenshot confusion

The garbled dropdown the owner saw on mobile-web ("1,5 метра / один метр / 500 тысяч / 50 тысяч")
is now explained with higher confidence: Studio's generation controls bundle at least two unrelated
settings into one picker — a **physical scale preset** (1.5 m / 1 m object size) and a **polygon
budget preset** tied to PolyGen 1.5's reduction levels (the third-party-claimed 40K–1.5M range
would plausibly surface as rounded presets like "500K / 50K" polys). This is consistent with the
owner's own assessment that the mobile-web wrapper is a thin, under-localized skin and the real
product surface is the desktop Studio.

---

## Part 2 — Nomad Sculpt

### 2.1 What it is

Nomad Sculpt (developer: Stéphane Ginier, also known for the original Sketchfab web viewer) is a
touch/pencil-first digital sculpting app, originally iPad-only, now cross-platform. It is widely
cited as the dominant mobile sculpting tool for hobbyists and working 3D artists doing concept/
blockout work on a tablet.
([cgchannel.com launch coverage](https://www.cgchannel.com/2020/08/check-out-nomad-a-neat-new-ios-and-android-sculpting-app/))

### 2.2 Core feature set

- **Sculpting brushes**: Clay, Crease, Trim, Smooth, Mask, and others, tuned for touch/pencil
  pressure input.
- **Boolean/hardsurface tooling**: a trim-boolean cutting tool with lasso and rectangle selection
  shapes, aimed specifically at hardsurface (not just organic) modeling.
- **Voxel remeshing**: re-meshes the whole model to a uniform resolution on demand — used to
  quickly block out a rough shape early, then refine.
- **Dynamic topology**: locally subdivides mesh detail under the brush as you sculpt, giving
  automatic, local level-of-detail; layers update automatically even as topology changes under them.
- **Multiresolution sculpting**: move between multiple resolution levels of the same mesh,
  supporting a coarse-to-fine workflow.
- **Layers**: sculpting and painting operations both record into separate, editable layers for
  non-destructive iteration.
- **Primitives**: cylinder, torus, "triplanar voxel," and other base shapes to start new pieces.
- **Vertex painting**: per-vertex color, roughness, and metalness, with material-preset management;
  rendering supports both Matcap (stylized) and PBR preview.
- **Posing**: the app supports pose/deformation workflows for figure work (referenced across review
  coverage; not itself a rigging system).
- **Import/export**: OBJ, STL, and glTF; only glTF round-trips paint/layer data — OBJ/STL lose that
  information on export.
  ([cgchannel.com feature rundown](https://www.cgchannel.com/2020/08/check-out-nomad-a-neat-new-ios-and-android-sculpting-app/);
  [Hunyuan Polygen-unrelated APK changelogs, apkmirror.com](https://www.apkmirror.com/apk/hexanomad/nomad-sculpt))

Explicitly **not** included: UV mapping, hair/fabric simulation, and full production-renderer
features — multiple forum sources confirm artists typically sculpt in Nomad, then move to Blender/
Maya for retopology, UV unwrap, and texturing.
([Nomad Sculpt community forum thread — "Is Nomad Sculpt good enough to be used professionally"](https://forum.nomadsculpt.com/t/is-nomad-sculpt-good-enough-to-be-used-professionally-exclusively-compared-to-blender-zbrush-etc/2529))

### 2.3 Why users say it beats Blender sculpt mode / ZBrush / Forger

From the official forum and independent reviews:

- **Interaction model, not feature count, is the differentiator.** Users describe the workflow as
  "similar to Blender or ZBrush but much more user-friendly" — the underlying sculpting concepts
  (brushes, dynamic topology, voxel remesh) are the same ones ZBrush/Blender use; Nomad's edge is a
  touch/pencil-first UI designed around gesture, not a mouse-and-keyboard-ported one bolted onto a
  tablet.
- **ZBrush's menu density is the explicit foil.** Reviewers call out ZBrush's small, deeply nested
  menus as tedious to navigate on any input device, let alone touch; Nomad's flatter, radial/
  gesture-driven tool access is cited as the direct improvement.
- **Responsiveness on mobile GPUs.** Some users report Blender's sculpt mode feels "laggy" with
  dynamic topology or voxel remeshing even on desktop GPUs, while Nomad (built mobile-first, so
  performance-constrained from day one) stays responsive at comparable complexity.
- **Learning-curve transfer, not learning-curve avoidance.** The community view is not "Nomad is
  easier so you never need ZBrush" — it's "learning to sculpt in Nomad reduces your ZBrush learning
  curve, because you already know how to sculpt" — i.e., Nomad teaches the transferable mental model
  (brush pressure, dynamic detail, layers) without ZBrush's interface tax.
- **Portability as a workflow enabler, not just a gimmick.** Being iPad/Pencil-native lets people
  sculpt outside a studio/desk setup; several reviewers treat this as a genuine workflow advantage
  for ideation and travel, not merely a convenience.
- **Candid limits acknowledged by the community itself**: no UV mapping, no advanced retopology, no
  hair/fabric simulation — consensus is Nomad is "an accessible entry point and supplementary tool
  within a broader pipeline," not a full standalone replacement for game-asset production.
  ([Nomad Sculpt forum thread](https://forum.nomadsculpt.com/t/is-nomad-sculpt-good-enough-to-be-used-professionally-exclusively-compared-to-blender-zbrush-etc/2529);
  [digitalproduction.com on the desktop beta](https://digitalproduction.com/2025/06/02/nomad-sculpting-on-desktop/))

### 2.4 Pricing and platform availability

Nomad uses a **one-time purchase per platform**, not a subscription — but "per platform" is literal:
licenses do **not** transfer across ecosystems, and the developer states plainly there is no
cross-store license-sharing agreement (e.g., buy on Android, then get an iPad, you pay again).

- **iPadOS/iOS**: $19.99 (App Store; €18.99 in the Eurozone listing). Full version, perpetual
  license for the current major version.
- **Android (Google Play)**: $15, with a free trial available before purchase (the developer notes
  older Android devices can struggle, hence the trial).
- **Desktop (Windows/macOS, Linux community builds referenced)**: currently a **free public beta**,
  explicitly **not production-ready** ("bugs, crashes, or missing features may occur"); claims
  feature parity with the iPad version (same brush set, Matcap/PBR rendering, vertex painting,
  multiresolution sculpting, layers, OBJ/STL/glTF I/O). Pricing post-beta is explicitly undecided —
  Tencent-style freemium vs. a paid desktop license is still an open question per the developer's
  own FAQ. Some resale/listing aggregators quote a future desktop price near $35, but this is not
  confirmed by the developer and should not be treated as fact.
- **visionOS**: the app is listed as compatible with visionOS 1.0+, at the same App Store price
  point as iPadOS (not independently confirmed as a distinct SKU).
  ([nomadsculpt.com official FAQ](https://nomadsculpt.com/manual/faq);
  [digitalproduction.com desktop beta coverage](https://digitalproduction.com/2025/06/02/nomad-sculpting-on-desktop/))

Rating signal: 4.8/5 on the Apple App Store across 11.3K+ ratings — a strong satisfaction signal for
a $19.99 one-time creative tool, worth noting as a pricing-model data point (one-time purchase with
no feature paywalling scores very well with this audience).

---

## Part 3 — So what for SOVA

Grounded in the current registry: SOVA already spans photo/scan→mesh generation, mesh editing,
mesh→exact-CAD reverse engineering, an OCCT-backed CAD feature tree, an FDM slicer, LiDAR room/
building scanning, multi-format import/export, and web/desktop(Tauri)/mobile clients plus a
marketplace (`docs/v2/v1_core/FEATURE_REGISTRY.txt`, `docs/FEATURE_REGISTRY_ADDENDUM.md`). The
owner's stated goal: SOVA should be easier for total beginners while staying comprehensive for
professionals — "more beautiful, simpler, more technological" than both Hunyuan 3D and Nomad
Sculpt.

### 3(a) — UX/interaction patterns worth adopting

1. **Bundle generation controls by outcome, not by parameter.** Hunyuan's confirmed failure
   (§1.7) is a cautionary example — a scale preset and a polygon-budget preset collapsed into one
   unlabeled dropdown confused even a native-reading user. SOVA's generation flow (`apps/web`
   Studio "Создать" entry, the mobile "+" sheet per `COMPETITOR_UI_ANALYSIS.md`) should keep the
   inverse discipline already partly in place: expose scale and polygon/decimation target as two
   clearly labeled controls, each with a short "what this is for" caption, never merged into one
   picker. This is a "don't repeat their mistake" item, concretely actionable in
   `apps/web`'s generation-settings component and the mobile creation sheet.
2. **Multi-view input ladder as a discoverable, not hidden, upgrade path.** Hunyuan's generation
   quality visibly improves as more reference views are supplied (4 views at 2.x, up to 8 at
   Studio 1.2). SOVA's photo/scan→mesh flow already accepts "несколько изображений → 3D"
   (`FEATURE_REGISTRY.txt` §1). Consider surfacing a simple in-flow nudge — "add another angle for
   a sharper result" — directly in the capture/upload step on mobile and web, rather than leaving
   multi-image quality gains undiscoverable. This is additive UI, not new backend capability.
3. **Nomad's gesture-first tool access over menu-dense palettes.** The clearest, most portable
   lesson from Nomad is architectural-UI, not feature-list: primary sculpt/mesh-edit tools (brush
   type, boolean trim, layer toggle) sit in a flat, thumb-reachable radial/gesture layer instead of
   nested menus, which is exactly the contrast users draw against ZBrush. SOVA's mesh-edit panel
   already has move/extrude/inset/delete/bevel and detail tools (`COMPETITOR_UI_ANALYSIS.md`,
   "Прямое polygon/mesh-редактирование"); on mobile specifically, where the addendum notes the
   full topology/grid/snap/symmetry panel is not yet built (F-086's "mobile ещё нет" gap), this is
   the moment to design that panel gesture-first rather than port the desktop panel verbatim.
4. **Layers as the mental model for non-destructive iteration, surfaced plainly.** Nomad's "record
   sculpting and painting as separate layers, auto-updated under topology change" is a simpler
   mental model for a beginner than SOVA's (more powerful) typed B-Rep feature stack / mesh-edit
   step stack (T-239/T-240 in `COMPETITOR_UI_ANALYSIS.md`). Don't change the underlying engine —
   SOVA's stack is strictly more capable (typed steps with tolerance, reorderable, OCCT-backed) —
   but consider labeling/visualizing it in the UI using Nomad's "layers" vocabulary and a similar
   flat history list, rather than exposing feature-tree jargon to a first-time user.
5. **One-time-purchase-sized trust signal.** Nomad's 4.8/5 at a $19.99 one-time price is a useful
   external data point for SOVA's own pricing/marketplace positioning conversation (not a UX
   change) — simple, transparent, non-paywalled core tools score very well with exactly the
   "prosumer creator" audience SOVA's beginner-to-pro range also targets.

### 3(b) — Technical/architecture ideas worth evaluating

1. **PolyGen-style learned retopology as a distinct, reusable service.** Hunyuan's PolyGen 1.5 is
   notable less for being "Hunyuan's feature" than for being architected as a standalone
   mesh-in/mesh-out retopology service callable on *any* source mesh (§1.2). SOVA's registry already
   lists quad retopology as a confirmed gap ("Quad retopology и AI PBR: Отсутствует" in
   `COMPETITOR_UI_ANALYSIS.md`). Worth an engineering evaluation (not a commitment) of whether a
   similar learned, autoregressive retopology step belongs *after* SOVA's existing AI Repair stage
   for the specific case of scan-derived or generated meshes destined for game/animation export
   (`FEATURE_REGISTRY.txt`'s "Game/CG pipeline" section already names low-poly/retopology/LOD as a
   roadmap item) — but it should remain opt-in and clearly separate from SOVA's CAD-accuracy path
   (see 3c).
2. **Component decomposition (PartGen-style) as a generation-time step for assembly-aware output.**
   Hunyuan's PartGen 1.5 brush-refines a generated model into separately editable parts at
   generation time. SOVA's "AI Assembly: понимание нескольких деталей и предложение сборки"
   (`FEATURE_REGISTRY.txt`, "Библиотека компонентов и механизмов") is conceptually adjacent but
   currently framed as post-hoc assembly reasoning over existing parts. Evaluate whether
   decomposition-at-generation-time (so a generated mesh arrives pre-split into printable/editable
   components, each watertight) is worth prioritizing — it would compose naturally with SOVA's
   existing "Cut into parts" feature (F-081) rather than duplicating it.
3. **A documented VRAM/latency cost table, published like Hunyuan's.** Hunyuan documents concrete
   VRAM tiers (10/21/29 GB) and generation-time tiers (Rapid 2–3 min, Pro 3–6 min) publicly. Even
   directionally-sourced, this is useful transparency SOVA could match for its own generation
   pipeline (`04_AI_3D_PIPELINES.docx`) — setting honest expectations is consistent with SOVA's
   existing "no fake precision" posture (see 3c) and reduces support burden from users guessing why
   a generation is slow or fails.

### 3(c) — Explicit non-recommendations

SOVA's generative mesh output deliberately returns honest `no_color_data` instead of guessed
texture, and mesh→CAD conversion **fails closed** (refuses, rather than approximates) when a region
is non-planar, holed, or disconnected (`COMPETITOR_UI_ANALYSIS.md`, T-247 scope notes). That
positioning rules out importing several of these products' most appealing-looking patterns:

1. **Do not adopt "always produce a textured, finished-looking result" as a norm.** Hunyuan's
   demo-friendly promise — any input, in 30 seconds, produces a fully textured PBR mesh — is built
   for content/game-asset speed, where a plausible-looking wrong answer is an acceptable trade.
   SOVA's reverse-engineering and CAD paths exist specifically to *not* do this: guessed texture or
   guessed geometry on a part someone will manufacture or structurally trust is a correctness
   regression, not a feature gap. Keep `no_color_data` and fail-closed CAD conversion exactly as
   designed; do not let a "be more like Hunyuan" instinct erode them.
2. **Do not adopt Nomad/Hunyuan's "triangle soup, fix it later (or don't)" tolerance for
   non-manifold output as acceptable default output quality.** Hunyuan 2.x's own well-documented
   defect (§1.2) is the thing SOVA's AI Repair already exists to catch; the lesson from Hunyuan is
   "even a well-funded SOTA generator ships this defect by default," which argues for keeping
   AI Repair mandatory-by-default on generated/scanned input, not for relaxing SOVA's own repair
   gate to match competitor speed.
3. **Do not adopt per-platform, non-transferring one-time-purchase licensing as a model for a
   synced, cross-device product.** Nomad's "buy again if you switch platforms" model works for a
   single-developer indie app with no backend account system; it directly conflicts with SOVA's
   existing "Единый аккаунт и синхронизация проектов между устройствами" commitment
   (`FEATURE_REGISTRY.txt`, "Платформа и collaboration"). This is a pricing-model anti-pattern for
   SOVA specifically, not a general criticism of Nomad's choice for its own context.
4. **Do not treat Hunyuan's "automatic rigging/animation preset" as a precision commitment.**
   Hunyuan's auto-rig-and-preview is explicitly a content/animation-preview convenience feature,
   not a dimensionally-verified output. If SOVA ever extends into character/game-asset rigging
   (currently explicitly out of scope — "Риг, анимация, симуляции... не входят в текущий путь
   продукта," `COMPETITOR_UI_ANALYSIS.md`), it should not borrow Hunyuan's "looks animated, so it's
   done" framing; any SOVA rigging feature would need the same fail-closed honesty standard as
   mesh→CAD, e.g., flagging non-standard topology rather than silently producing a broken rig.
5. **Do not copy Hunyuan Studio's closed-beta-by-application gating as UX inspiration.** It is a
   capacity-management device for a free/subsidized compute-heavy generator, not a usability
   pattern; it has nothing to teach SOVA's onboarding design and should not be cited alongside the
   genuine UX lessons in 3(a).

---

## Sources (consolidated)

- Hunyuan3D 2.1 model card and technical report: https://huggingface.co/tencent/Hunyuan3D-2.1 ,
  arXiv:2506.15442
- Hunyuan3D overview: https://comfyui-wiki.com/en/models/hunyuan3d
- Tencent global Hunyuan 3D Engine announcement: https://www.tencent.com/en-us/articles/2202235.html
- Tencent professional AI 3D workbench coverage (Chinese): https://www.stdaily.com/web/gdxw/2025-09/25/content_407381.html
- Hunyuan 3D Studio feature overview (Chinese): https://ai-bot.cn/hunyuan3d-studio/
- Hunyuan3D 2.0 release notes (Chinese): https://comfyui-wiki.com/zh/news/2025-01-24-tencent-hunyuan3d-2-release
- Hunyuan3D 2.0 geometry/texture architecture (Chinese): https://comfyui-wiki.com/zh/news/2025-03-19-tencent-hunyuan3d-2-release
- Hunyuan Polygen 1.5 essentials: https://help.scenario.com/articles/5113903414-hunyuan-polygen-1-5-the-essentials
- Hunyuan Polygen 1.5 model page: https://www.scenario.com/models/hunyuan-polygen-15
- Hunyuan 3D pricing aggregation: https://costgoat.com/pricing/hunyuan-3d
- Tencent Cloud Hunyuan 3D Global documentation: https://www.tencentcloud.com/document/product/1284/75281
- Nomad Sculpt launch coverage: https://www.cgchannel.com/2020/08/check-out-nomad-a-neat-new-ios-and-android-sculpting-app/
- Nomad Sculpt desktop beta coverage: https://digitalproduction.com/2025/06/02/nomad-sculpting-on-desktop/
- Nomad Sculpt official FAQ (pricing/platforms/licensing): https://nomadsculpt.com/manual/faq
- Nomad Sculpt community forum — professional-use discussion: https://forum.nomadsculpt.com/t/is-nomad-sculpt-good-enough-to-be-used-professionally-exclusively-compared-to-blender-zbrush-etc/2529
- Nomad Sculpt Android/visionOS pricing round-up: apkmirror.com, apppricinglab.com, splitmetrics.com
  listings for package `com.stephaneginier.nomad` / App Store id1519508653

## Internal references consulted (SOVA repo, not re-stated here)

- `/home/dev/projects/sova_3d/docs/v2/v1_core/FEATURE_REGISTRY.txt`
- `/home/dev/projects/sova_3d/docs/FEATURE_REGISTRY_ADDENDUM.md`
- `/home/dev/projects/sova_3d/docs/COMPETITOR_UI_ANALYSIS.md`
- `/home/dev/projects/sova_3d/apps/mobile`, `/home/dev/projects/sova_3d/apps/desktop` (directory
  structure only, for grounding recommendations to real app targets)
