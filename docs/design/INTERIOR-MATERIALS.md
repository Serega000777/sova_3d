# Interior surface materials: bounded first increment (design)

Status: design only; no product code is changed by this document. This closes the design
blocker behind item 22 in `docs/COMPETITOR_UI_ANALYSIS.md` ("Отделка и материалы
интерьера"). The proposal is grounded in direct reads of
`services/api/app/services/scenes.py`, `services/api/app/api/{scenes,painting,exports}.py`,
`services/api/app/services/painting.py`, `services/api/app/jobs/{paint_model,export_job}.py`,
`services/api/app/engineering/facade.py`, `services/api/app/api/facades.py`,
`services/worker/worker/exporters.py`, both current viewers, and the material/paint history in
`docs/{IMPLEMENTED,IN_PROGRESS}.md` -- not in an assumed generic "materials" subsystem.

## 0. What exists today, exactly

1. **The scene graph has no appearance primitive.** A stored object node has identity,
   hierarchy, visibility, a transform, an asset or instance target, and an optional furniture
   footprint (`services/api/app/api/scenes.py:21-35`). `resolve_scene()` validates those fields
   and resolves an asset/world transform (`services/api/app/services/scenes.py:132-180`), but
   there is no colour, finish, texture, material slot, or surface role. Historical one-model
   versions are exposed as a backward-compatible generated `object_1` node
   (`services/api/app/services/scenes.py:99-119`).
2. **Paint is a different abstraction.** `POST /models/{version_id}/paint` accepts a version-wide
   list of free strokes plus an optional base colour (`services/api/app/api/painting.py:18-54`).
   The paint worker keeps the shape asset unchanged and writes a coloured GLB preview plus
   `provenance["paint"]`; it does not assign a reusable catalogue finish to a scene node.
3. **Facade finishes are semantic but facade-specific.** `SurfaceMaterial` is keyed by exact
   facade roles and carries a colour plus an optional `material_id`
   (`services/api/app/engineering/facade.py:54-75`). `FacadeRequest` rejects duplicate and
   unknown semantic surface keys (`facade.py:132-148`), and the edit endpoint carries only keys
   that still exist while reporting dropped keys (`services/api/app/api/facades.py:277-339`).
   Those roles are generated from one proved rectangular-house operation plan; arbitrary room
   meshes and furniture have no corresponding `wall.*`/`floor.*` keys.
4. **The existing `materials` table is a print-material catalogue, not a finish catalogue.** Its
   fields are density, price/kg, shrinkage and minimum printable wall thickness, with ids such as
   `pla` (`services/api/app/models/printing.py:44-59`). It cannot honestly represent wall paint
   gloss, oak grain, stone or ceramic tile. Reusing those rows would conflate manufacturing
   assumptions with visual appearance.
5. **Scene export currently carries only geometry and placement.** The API sends `asset_id`,
   format and `world_transform` per visible object (`services/api/app/api/exports.py:90-109`).
   Worker `SceneMeshInput` has the same four concerns
   (`services/worker/worker/exporters.py:60-75`); composition loads meshes with
   `skip_materials=True`, transforms them, concatenates them and writes one mesh
   (`exporters.py:201-215,254-268`). A new viewer-only material would therefore be lost in GLB.
6. **The two viewers do not yet share a scene appearance path.** Web scene parts contain only
   URL/format/transform (`apps/web/src/components/ModelViewer.tsx:58-64`) and web reduces a GLB
   to the first mesh geometry/vertex colours (`ModelViewer.tsx:576-595`). Mobile does preserve
   the first GLB material (`apps/mobile/src/ModelViewer.tsx:307-353`), but neither viewer can
   consume a server-declared per-node finish. Parity must be implemented, not inferred from the
   fact that both use Three.js.

## 1. Scope and product boundary

### In scope

- A small, deterministic, in-repository interior finish catalogue exposed by the API: paint
  colours with hex and gloss percentage, plus one or two basic repeating maps in each bounded
  texture family (wallpaper, decorative plaster, wood, stone and ceramic tile).
- One catalogue material assigned to one **object `SceneNode` as a whole**. A material change
  creates a new immutable project version; the source geometry asset is not rewritten.
- The reference's four catalogue tabs -- `Стены`, `Пол`, `Мебель`, `Плитка` -- as filters over
  that bounded catalogue, with paint cards showing hex and gloss. They are library/navigation
  categories, not a claim that the server has inferred whether an arbitrary triangle is a wall.
- Web and mobile controls against the currently selected scene object, and the same material
  interpretation in web viewer, mobile viewer, and standard GLB scene export.
- Carry-forward across rename, reparent, transform/visibility changes, and node-specific
  geometry replacement, with an explicit dropped-node report when a material-assigned object no
  longer exists.

### Explicitly out of scope

- **Per-wall, per-face, region-mask, multi-slot or layered materials.** A scanned room or imported
  shell that is one node receives one finish over that whole node. To finish its walls and floor
  independently, those surfaces must already be separate scene nodes; automatic room-surface
  segmentation is a later increment.
- Wallpaper alignment controls, grout width, tile layouts, normal/height/displacement maps,
  physically measured BRDFs, UV editing, and photoreal texture-pattern rendering. This increment
  stops at solid PBR colour plus one basic repeating base-colour texture map.
- Any AI or heuristic `Похожие оттенки` recommendation engine. No suggestion is shown merely
  because colours are close in RGB.
- A dedicated synchronized `До/После` split/reveal UI. Immutable parent/current versions make a
  later comparison implementation straightforward, but ordinary version navigation is not
  presented as the reference's comparison control.
- Supplier catalogue, price/area estimate, user-uploaded materials, and facade variant reuse.
- A generated isometric room cutaway or semantic wall/floor detection. Existing orbit/isometric
  viewing can display a scene that already contains separate room/furniture nodes; this increment
  does not invent missing geometry.

## 2. Granularity decision: one material per `SceneNode`

**Decision: use per-object-node assignment, not per-face assignment, for the first increment.**

This is the smallest model that delivers genuine value in the current product:

- T-241 already gives every independently selectable room part or furniture item a stable node
  id, one geometry source, hierarchy and immutable rebuild path. Furniture placed through the
  shipped catalogue is already a separate node. Changing an entire selected floor slab, wall
  object, tile panel, cabinet or sofa is therefore a real material edit, visible everywhere the
  scene is used.
- A face-level design has no stable identity to attach to. Current scene data stores asset plus
  transform, while imported/scanned STL triangles and OCCT tessellation can be reordered by a
  repair or geometry rebuild. Using a triangle/face index would repeat the exact problem the
  facade implementation avoided by using semantic keys. A correct per-face increment first
  needs room-surface segmentation and durable semantic face identities; neither exists.
- Adding generic slots/masks now would pre-decide that future segmentation model without evidence.
  One node/one material is easy to validate, carry, export and explain: "the selected object is
  finished as a whole." It is deliberately less general, but unlike a cosmetic panel it works
  end to end for every already-separate object.

The UI must keep this boundary visible: while an object is selected it shows
`Материал применяется ко всему выбранному объекту`. The reference tabs filter the catalogue;
they do not alter selection granularity. No click on one triangle may appear to select a wall
surface in this increment.

## 3. Catalogue decision: a separate bounded interior catalogue

**Decision: reuse the facade system's identity/carry-forward discipline, but do not reuse its
surface keys, request model, or print-material rows.**

The reusable pattern is:

```
stable role identity -> validated catalogue id -> immutable appearance snapshot
```

For facades, the stable role is a generated `surface_key`; here it is the `SceneNode.id`. Facade
carry-forward keeps only roles that still exist and reports removed ones. Interior assignment
does the same by node id (§5). The concrete facade data is not reusable: its role set is derived
from exact-house dimensions/openings, its optional pricing belongs to facade variants, and its
`material_id` validation currently points at print profiles rather than an interior finish.

### 3.1 Canonical catalogue

Add one server-owned module and immutable texture resources under
`services/api/app/interior_materials/`. Both API and the production worker image already include
`api/app` (`services/api/Dockerfile` copies it into both targets), so this is one source of truth,
not separately maintained web/mobile lists.

Each entry has this bounded shape:

```json
{
  "id": "interior.paint.warm-white-matte.v1",
  "name": "Warm white, matte",
  "name_ru": "Тёплый белый, матовый",
  "tabs": ["wall", "furniture"],
  "kind": "paint",
  "base_color": "#F2EBDD",
  "gloss_pct": 8,
  "texture": null
}
```

Textured entries replace `texture: null` with
`{"sha256": "...", "tile_size_mm": 300}` and use one of
`wallpaper | plaster | wood | stone | tile`. Rules:

- ids and texture hashes are immutable and add-only; changing colour/gloss/map creates a new id;
- `base_color` is six-digit sRGB hex, `gloss_pct` is an integer 0-100, and
  `roughness = clamp(1 - gloss_pct / 100, 0.04, 1.0)` everywhere;
- metallic is always `0`, opacity always `1`, and there are no normal/roughness maps in this
  increment;
- a texture is a small power-of-two PNG, maximum 512x512 and 256 KiB, with a positive
  `tile_size_mm` between 10 and 5000;
- the initial catalogue is bounded (target 12-16 entries): several paints plus at most two maps
  per texture family. Expansion is additive data work, not a database migration.

`GET /interior-materials` returns the descriptors and an immutable texture URL containing the
SHA-256. `GET /interior-materials/textures/{sha256}.png` serves only known catalogue resources
with immutable cache headers. There is no upload or arbitrary file path.

### 3.2 Stored appearance snapshot

The scene provenance schema advances to version 2. Every object node may have:

```json
"appearance": {
  "schema_version": 1,
  "catalog_material_id": "interior.paint.warm-white-matte.v1",
  "base_color": "#F2EBDD",
  "gloss_pct": 8,
  "roughness": 0.92,
  "texture_sha256": null,
  "texture_tile_size_mm": null
}
```

The server copies the normalized catalogue values into the node rather than storing only a
mutable lookup id. This makes a project version self-describing and immutable. Texture bytes are
content-addressed by the stored hash and retained add-only. `catalog_material_id` remains for UI
labels/audit, but rendering uses the validated snapshot. A group cannot have appearance.

This is JSON provenance, like the scene itself; no Alembic migration is needed. Scene schema v1
remains readable as `appearance = null`. Any new write emits schema v2. Unknown scene schema
versions remain fail-closed rather than silently discarding materials.

## 4. API and immutable version operation

### 4.1 Read contract

`SceneNodeOut` gains `appearance: SceneAppearanceOut | null`; generated contracts carry it to
both clients. `SceneAppearanceOut` includes the stored fields plus resolved `name`, `name_ru` and
`texture_url` from the retained immutable catalogue entry/hash.

The editable `SceneNode` request does **not** accept arbitrary appearance fields. Existing scene
tree clients therefore cannot forge colours, texture URLs or hashes through
`POST /models/{version_id}/scene`; appearance is changed only by the endpoint below and is
server-carried through ordinary scene edits.

### 4.2 Assign/clear contract

```
POST /models/{version_id}/interior-material
{
  "scene_node_id": "chair_1",
  "catalog_material_id": "interior.wood.oak-natural.v1" | null,
  "label": "Oak chair"
}
```

- Requires editor role, a finalized version, and a currently existing object node. Group,
  missing, cross-project and duplicate node ids are rejected through the existing scene
  resolver. `null` explicitly clears the node's material.
- A non-null id must exactly match the server catalogue. The server creates the normalized
  immutable snapshot; the client cannot submit hex, gloss, roughness or a texture URL.
- The operation creates and finalizes one child version synchronously, as scene hierarchy edits
  already do. Geometry assets, transforms, visibility, footprints, operation rows and modifier
  rows are preserved. No render job is required because appearance is declarative; GLB baking
  happens only when the user requests export.
- Provenance records
  `interior_material_edit: {source_version_id, scene_node_id, from_material_id,
  to_material_id, dropped_node_ids: []}`. The project head advances through the same
  `create_version_internal`/`finalize_version` path as other immutable scene edits.
- Assigning the already-effective material is rejected as a no-op; clearing an unassigned node
  is also rejected. This prevents empty version spam.

A legacy one-model version is materialized as explicit scene schema v2 using its generated
`object_1` node during the first assignment. This follows the existing backward-compatibility
path rather than creating a second single-model storage format.

## 5. Carry-forward and drop rules

`SceneNode.id` is the stable role for this bounded model. Material follows that role, not a node
name, parent name, list position, asset id, triangle index or resolved instance target.

| Version rebuild | Rule |
| --- | --- |
| Rename, reparent, transform or visibility edit with the same object node id | Carry the exact appearance snapshot. |
| Node-specific geometry edit via `replace_object_asset()` with the same object node id | Carry it. Geometry changed, but the semantic object role did not, just as a facade wall role survives a rebuild. |
| Make-unique of an instance while keeping its node id | Carry it. |
| New duplicate/instance with a new node id | Start unassigned. No implicit coupling to the source node's later material. |
| Object node removed | Drop the assignment and record the id in `dropped_material_node_ids`. |
| Object changed to group | Reject if appearance was explicitly supplied; normal server carry drops it and records the id because groups cannot be finished. |
| Node id changes | Treat as delete + add: old assignment is dropped; never guess from equal name, equal asset or nearest transform. |
| Scene schema v1 read | Appearance is absent; no synthetic default is persisted. |

Implementation consequence: every stored-node serializer must include `appearance`. Today both
`replace_object_asset()` and `create_scene_version()` rebuild whitelists of fields
(`services/api/app/services/scenes.py:395-429,435-460`); merely adding a Pydantic field would
silently lose it. The carry helper must be centralized in `app.services.scenes` and used by:

- `create_scene_version()` for hierarchy edits;
- `replace_object_asset()` for node-specific mesh edits;
- furniture scene rebuilds, which call `stored_nodes()`;
- marketplace scene construction/acquisition when it copies existing scene nodes;
- the dedicated material assignment operation.

`resolve_scene()` validates appearance on every path: exact keys only, finite/bounded numeric
values, known immutable texture hash, object-only, and snapshot/hash equality with a retained
catalogue revision. This mirrors transform/footprint deep validation instead of trusting one API
entry point.

## 6. Viewer and GLB export parity

Appearance is not complete until all three consumers interpret the same snapshot.

### 6.1 Canonical material interpretation

Web and mobile extend `ViewerScenePart` with the resolved appearance and build a
`MeshStandardMaterial` from the same fields:

- sRGB `base_color`;
- `roughness` from the stored snapshot, `metalness = 0`;
- optional exact PNG selected by `texture_sha256`, repeat wrapping, no filtering-specific colour
  correction beyond the same sRGB declaration;
- selection highlight changes emissive only and never replaces the base material.

For a texture on geometry without UVs, all three consumers use one specified basic box projection
in **object-local platform millimetres before the world transform**:

1. de-index to triangle corners;
2. compute each triangle normal and choose the largest absolute component, tie-breaking X, then
   Y, then Z;
3. project X-dominant triangles as `(y, z)`, Y-dominant as `(x, z)`, and Z-dominant as `(x, y)`;
4. divide both coordinates by `texture_tile_size_mm` and use repeat wrapping.

The deliberately simple projection can show seams on curved furniture; that is within the basic
texture boundary. Paint needs no UVs. Shared contract fixtures contain exact triangle positions,
dominant-axis decisions and expected UVs; TypeScript (web/mobile) and Python (export worker) must
pass the same fixture corpus.

### 6.2 GLB export

`api/exports.py` adds the validated appearance snapshot to each visible scene entry. The job
handler passes it into an extended `SceneMeshInput`; the worker validates it again. For GLB:

- apply the canonical UV projection before each node's world transform;
- create one PBR material per distinct appearance snapshot, embed the exact catalogue PNG when
  present, and preserve node names/transforms as separate GLB scene objects;
- do not concatenate all objects into one material-less mesh. The current
  `skip_materials=True` + `trimesh.util.concatenate()` path
  (`services/worker/worker/exporters.py:201-215,254-268`) must be replaced for GLB scene output;
- an unassigned node keeps the current neutral fallback in this bounded path; an assigned node
  must never silently fall back because its texture is missing.

STL remains geometry-only by format and is not advertised as carrying a finish. 3MF/FBX material
parity is not part of this increment; their existing geometry export remains, with an explicit UI
note where relevant. The acceptance claim is web + mobile + **standard GLB**.

"Same material" means the same base colour, texture bytes, UV projection/repeat and PBR scalar
values. Different viewport lights may produce different pixels; neither client may substitute a
different swatch or drop the texture.

## 7. Web and mobile interaction

Both clients use the same API and server catalogue:

1. Select one effective-visible object in the existing scene viewer/tree.
2. Open `Интерьер` / `Материалы` and choose one of the four tabs. Tabs filter catalogue `tabs`;
   they do not mutate or infer the selected node's type.
3. Paint cards show swatch, name, hex and `Глянец N%`. Textured cards show the actual immutable
   tile thumbnail and category label.
4. `Применить к объекту` calls the assignment endpoint, waits for the returned child version,
   advances to it, and reloads the scene. `Сбросить материал` sends `null`.
5. The panel always names the selected node and shows the whole-object scope warning. With no
   object selected, apply is disabled. Groups and hidden/effectively hidden objects cannot be
   targeted from the panel.

There is no optimistic local-only material state. A card may be previewed on hover/press only as
an explicitly labelled transient preview; the persisted viewport changes after the immutable
version succeeds. Mobile uses a sheet, web uses the existing Studio inspector/rail pattern.

## 8. Fail-closed boundary

| Input/state | Outcome |
| --- | --- |
| Known catalogue id + existing object node | New immutable version |
| Unknown/retired id, client-supplied colour/URL, texture hash not in catalogue | Rejected before version creation |
| Group, missing node, duplicate node id, broken instance, cross-workspace asset | Rejected by scene validation |
| Appearance on a group or malformed snapshot in stored provenance | Scene read/export rejected; never ignored |
| Deleted/renamed node during a server rebuild | Assignment dropped and reported; never retargeted by name, asset or position |
| Texture file absent or SHA mismatch in API, viewer fetch or worker | Apply/read/export fails visibly; no neutral fallback for an assigned material |
| Textured mesh has no UVs | Canonical bounded box projection; no guessed imported UV dependency |
| More than one material requested for one node | Rejected; one node has zero or one appearance in this increment |
| Attempt to target one face/region of a monolithic room node | Not representable; UI explains whole-object scope |

## 9. Touch list

Expected implementation surface (names may be adjusted, responsibilities may not):

- `services/api/app/interior_materials/` -- immutable catalogue, validators and PNG tiles.
- `services/api/app/api/interior_materials.py` -- catalogue/texture/assignment endpoints.
- `services/api/app/services/scenes.py` -- scene schema v2, appearance validation, centralized
  carry/drop helper and immutable assignment operation.
- `services/api/app/api/scenes.py` -- read-only appearance output contract.
- `services/api/app/api/exports.py`, `services/api/app/jobs/export_job.py` -- appearance in the
  scene export manifest.
- `services/worker/worker/exporters.py` -- validated appearance, canonical UV projection and
  material-preserving GLB scene output.
- `packages/contracts` -- generated API plus shared TS UV fixture runner/types.
- `apps/web/src/components/ModelViewer.tsx` and web project Studio -- material application and
  catalogue panel.
- `apps/mobile/src/ModelViewer.tsx`, `SceneTreeSheet.tsx`/project inspector -- the same material
  application and mobile sheet.
- Focused API/worker/contracts/web/mobile tests. No database model or Alembic revision.

## 10. Proof plan

### API / scene invariants

- Catalogue ids unique; every descriptor validates; every PNG hash/size/dimensions matches the
  manifest; changing an existing entry in place fails an immutable-catalogue snapshot test.
- Assign solid paint and textured material to legacy one-node and explicit multi-node versions;
  verify one child version, unchanged geometry asset ids, stored snapshot and head update.
- Unknown material, group target, missing node, malformed/forged appearance, texture hash mismatch,
  no-op reapply and no-op clear all fail before a version is created.
- Rename, reparent, transform and visibility edit preserve appearance for the same node id.
- `replace_object_asset()` preserves it for the edited node; delete and id change drop it and
  record only the actual old id. Equal name/asset on a different id does not carry.
- Existing schema-v1 and historical single-model versions remain readable with `appearance=null`.

### Viewer / contracts

- Contract tests validate the new scene output and reject malformed appearance values.
- Shared UV fixtures cover every dominant axis, negative coordinates, tie breaks and repeat
  scale; TypeScript and Python outputs match within a fixed tolerance.
- Web and mobile load the same solid/texture fixture, preserve base material under selection
  highlight, and dispose texture/material resources on version change.
- One reachable end-to-end UI test per client: select node -> tab -> material -> immutable version
  -> reloaded viewport. Physical-device texture memory/performance remains a release acceptance
  check, not something inferred from typecheck.

### Export parity

- A two-node scene with different materials exports GLB with two named objects/material bindings,
  embedded texture SHA, expected base colours, roughness values, UVs and world transforms.
- Re-import the GLB and assert geometry/bounds integrity plus material descriptors; compare a
  fixed camera render from web, mobile harness and exported GLB within a documented image
  tolerance.
- Missing texture, malformed appearance, empty visible scene and unsupported map dimensions fail
  closed. Existing material-less scene export fixtures continue to pass.
- Full API, worker, contracts, web and mobile suites; OpenAPI/generated types diff-clean; web
  production build and mobile production export. Browser and physical-device visual checks must
  be reported honestly rather than implied by automated tests.

## Summary

The first interior-material increment is **one immutable catalogue finish per object scene node**.
It deliberately reuses the facade system's stable-role/carry-drop principle, with `SceneNode.id`
as the role, but introduces a separate bounded interior catalogue because facade semantic keys
and print-material rows describe different domains. Appearance survives rename, reparent and
same-node geometry edits, drops only when that node role disappears, and is consumed from one
validated snapshot by web, mobile and GLB export. Per-face room finishing, advanced wallpaper/
texture fidelity, `Похожие оттенки`, and dedicated `До/После` remain explicit later increments.
