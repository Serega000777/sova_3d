# Marketplace rebuild: bounded first increment (design)

Status: design doc, no product code touched. Scoped from the owner's 10 reference mockups
(M01–M10) and their line-by-line audit against real code in
`docs/MARKETPLACE_UI_ANALYSIS.md`. Grounded in direct reads of
`services/api/app/models/marketplace.py`, `services/api/app/services/marketplace.py`,
`services/api/app/api/marketplace.py`, `services/api/app/payments.py`,
`services/api/app/services/fit.py`, `services/api/app/services/licensing.py`,
`services/api/app/services/entitlements.py`, `services/api/app/api/exports.py`,
`services/api/app/engineering/facade.py`, `services/api/app/models/printing.py`,
`services/api/app/services/assets.py`, `apps/web/src/app/market/page.tsx`,
`apps/web/src/app/market/[id]/page.tsx`, `apps/web/src/components/{ListingCard,PublishCard,
FitTestCard}.tsx` and the latest alembic revision (`0029_job_pause_resume.py`) — not from memory
of what they probably contain.

## 0. What exists today, exactly (recap)

The audit doc's table is the source of truth; this section only restates the five findings
this increment acts on, each with its code anchor:

1. **Payments are a stub.** `payments.py` defines `NoPayments` (402 on any priced charge) and
   `StubPayments` (fake success, "Development only"). Selected by one setting,
   `payments_provider: Literal["none", "stub"]`. No Stripe/ЮKassa/etc. exists.
2. **`Licence.commercial_use: bool` is stored, never read.** `marketplace.acquire()`
   (`marketplace.py:437–543`) never inspects it; `publish()` (`marketplace.py:213–280`) never
   inspects it either. The only licence field that is actually enforced is
   `attribution_required`, inside `licensing.set_license()` (`licensing.py:140–143`).
3. **Fit Test (`services/fit.py`) is real and strong, but workspace-locked and unwired.**
   `enqueue_fit_test` (`fit.py:48–93`) requires both versions' projects to share one
   `workspace_id` (`fit.py:66–67`, `"both parts must belong to the same workspace"`). No
   listing page calls it. `FacadeSide` (`engineering/facade.py:14`) is the literal
   `front/back/left/right` — no floor index, no compass.
4. **`PrintAnalysisRecord` is real and honest, never joined to a listing.**
   `models/printing.py:98–127` stores a per-version score/status/report;
   `GET /models/{version_id}/print-analyses` (`api/printing.py:538`) serves it.
   `MarketplaceItem`/`_listing_out()` (`api/marketplace.py:147–154`) never queries it.
5. **One listing = one version = one file, hard-locked.** `uq_marketplace_items_version_id`
   (`models/marketplace.py:60`) is a unique constraint on `version_id`. No cart table, no
   bundle/component table, anywhere in `app/models` or `app/services`.

## 1. Scope of this increment

**In scope — a real, shippable increment that does not block on a payment-provider decision:**

- UI/UX pass on the browse/category/search/product screens (M01–M04) to raise visual design
  and information density toward the mockups, without changing what data those screens read.
- Join `PrintAnalysisRecord` into listing reads and show an honest "Проверено на печать" badge.
- The cart + bundle **data model**: schema and service functions so a listing can hold several
  files and a user can hold several pending listings before paying. Checkout itself is not
  built (§3.5).
- Fail-closed enforcement of `Licence.commercial_use` at the two points where it currently does
  nothing: listing a priced item, and (self-declared) commercial export.
- Wiring a real "Примерить в проекте" action into the product page, using the existing Fit Test
  engine post-purchase, and a declared-dimension preview pre-purchase (§5).

**Out of scope — explicitly deferred, named so this doesn't get silently dropped:**

- **Payment-provider integration and the checkout flow** (M09's "Перейти к оплате"). Needs a
  Stripe/ЮKassa/other decision from the owner first; §3.5 names exactly what checkout will need
  from the schema this doc adds, so that decision doesn't require re-opening this design.
- **Category tree with per-subcategory counts** (M02). `MarketplaceItem.category` is one flat
  string (`models/marketplace.py:79`); a real tree needs a hierarchy table and aggregate counts.
  That is a data-model increment in its own right, not a UI pass, and is not bundled here.
- **Multi-format file choice per listing** (M04's STL/3MF picker). `model_asset_of()`
  (`services/assets.py:24–34`) resolves exactly one asset per version; offering several
  *formats* of the *same* model is a different feature from bundling several *different*
  models (§3), and is not addressed here.
- **PDF/DWG/XLSX document exports** (M06–M10 house package: 2D plans, facade sheets, BOM,
  explanatory note). The exporter only emits `stl/glb/3mf/fbx/step/iges`
  (`api/exports.py:27`) — none of those formats exist anywhere in the export pipeline. This is
  a separate, large increment (new renderers/writers), not a marketplace-layer change.
- **Yard/plot composition, area warnings, autotour/360** (M06–M10 yard). Needs plot-area
  metadata and a comparison step that doesn't exist on either side; not attempted here.
- **Moderation queue before publish** (M10). `publish()` sets `status=published` immediately
  (`marketplace.py:274`); gating that behind a review step is a workflow change orthogonal to
  the five gaps this doc closes, and is left for its own pass.
- **Floor index / compass orientation** for M08's "2 этаж, Северный фасад" targeting. Confirmed
  absent independently in `docs/design/HOUSE-AUTOLAYOUT-LT-SHAPES.md §3`
  ("there is no floor index anywhere in `FloorPlan`, `PlanRoom`, `PlanWall`, or `PlanOpening`").
  §5 below resolves M08 using only the addressing data that already exists.

## 2. Print-verified badge

**Rule:** show the checkmark only when it is true. `PrintAnalysisRecord.status` is one of
`green/yellow/red` (`models/printing.py:122`); only `green` earns "✓ Проверено на печать" — a
`yellow`/`red` record shows a different, non-checkmark status chip ("требует настройки печати" /
"не прошла проверку"), not nothing and not a false positive. This mirrors the audit's own
framing of the risk: a badge with no backing data would be worse than no badge.

**Data access, batched:** a new function in `services/api/app/services/printing.py`,
`latest_analyses_for(db, version_ids: list[uuid.UUID]) -> dict[uuid.UUID, PrintAnalysisRecord]`,
selects the newest `AnalysisKind.analysis` row (not `optimize` — that job produces a new model
version, not a verdict on this one) per `project_version_id` using a `ROW_NUMBER() OVER
(PARTITION BY project_version_id ORDER BY created_at DESC)` subquery, filtered to
`row_number = 1`. `api/marketplace.py`'s list-producing endpoints (`search`, `feed`,
`my_listings`, `project_listings`, `creator_page`) call this once per page with every listing's
`version_id`, instead of `_listing_out()` querying per row — avoids re-introducing an N+1 the
same way `_listing_out()` already avoids one for `model_asset_of`. The single-item path
(`get_listing`) can call it with a one-element list, no special-casing needed.

**Response shape:** `ListingOut` gets `print_verified: PrintBadgeOut | None`, where
`PrintBadgeOut = {status: Literal["green","yellow","red"], score: float, analyzed_at:
datetime}`. `None` means no analysis exists yet for that version — distinct from "status=red",
which means an analysis ran and failed.

**UI:** `ListingCard.tsx` and `market/[id]/page.tsx` render the badge chip, reusing the
`status-green/status-yellow/status-red` CSS classes `FitTestCard.tsx`'s `verdictClass` already
defines — no new visual language invented.

**Bundle interaction (forward reference to §3):** a bundle's badge is per-component. The
anchor listing's `print_verified` field reflects only its own anchor `version_id`; each
component in `components[]` carries its own `print_verified` the same way, shown in the
bundle-contents list, not rolled up into one listing-level claim.

## 3. Cart and bundle data model

### 3.1 Problem restated precisely

`MarketplaceItem.version_id` is unique (`uq_marketplace_items_version_id`). A listing is
exactly one version, which `_listing_out()` resolves to exactly one `model_asset_id`
(`api/marketplace.py:147–154`, `assets.model_asset_of`). M05 ("12 window/door modules"),
M06–M10 ("дом"/"двор", several files/objects as one product) and M09 (a cart of several
listings) each need more than that shape provides — one needs several files *inside* one
listing, the other needs several listings *held together* before one payment.

### 3.2 Bundles: `marketplace_item_components`

A new child table, additive only — zero changes to `marketplace_items` or
`marketplace_orders`:

```
marketplace_item_components
  id            uuid PK
  item_id       uuid FK -> marketplace_items.id ON DELETE CASCADE
  version_id    uuid FK -> project_versions.id ON DELETE CASCADE
  label         varchar(200) NOT NULL   -- e.g. "Окно 900×1500"
  sort_order    integer NOT NULL
  summary       jsonb NOT NULL          -- same shape as MarketplaceItem.summary, via _summary()
  UNIQUE (item_id, sort_order)
```

- `MarketplaceItem.version_id` keeps its existing meaning and its existing uniqueness: it is
  the **anchor** version — the one used for the card thumbnail, the `ModelViewer`, the print
  badge (§2), and the Fit Test target (§5). It is unchanged by this design: every listing that
  exists today keeps working exactly as before, with zero components rows.
- `version_id` inside `marketplace_item_components` has **no** uniqueness constraint across
  bundles: the same shared module (e.g. a railing used in several yard sets) may be a component
  of more than one listing. It also must not duplicate the bundle's own anchor `version_id`,
  nor another component row within the same bundle (`UNIQUE (item_id, sort_order)` plus an
  application-level check against repeats).
- Authorization stays simple: a component version must belong to the **same project** as the
  anchor listing. Whoever already has `editor` on the project (checked once, as `publish()`
  does today via `require_workspace_role`) can list any of that project's finalized sibling
  versions as components — no new cross-project authorization surface.
- A listing with zero components is a bundle of one (itself); `is_bundle` is computed as
  `len(components) > 0` at read time, not stored, so there is no denormalized flag that can
  drift from the truth.
- New service function `marketplace.publish_bundle(db, *, ..., component_version_ids:
  list[uuid.UUID])`: runs the exact same per-version checks `publish()` already runs (finalized
  state, has assets, same project) against every component, then inserts the component rows
  after the anchor `MarketplaceItem` is created. `publish()` becomes the zero-components case of
  `publish_bundle()` — implemented as `publish_bundle(..., component_version_ids=[])`, so there
  is one code path, not two to keep in sync.
- Pricing: unchanged. `MarketplaceItem.price_cents` prices the whole bundle; the mockups show
  no per-component pricing, so none is added.

### 3.2.1 Delivering every component on `acquire()` — not just the anchor

`acquire()` (`marketplace.py:437–543`) today copies exactly one `ProjectVersion`'s assets:
`source = db.get(ProjectVersion, item.version_id)`, then `_copy_asset` over `source.assets`
(`marketplace.py:471–492`). For a bundle, `item.version_id` is only the anchor — M05's window
modules or M06–M10's yard/house composition would stay in the creator's workspace after
purchase and never reach the buyer. This is closed by reusing, not inventing, the one mechanism
already in this codebase that composes several independent model assets into one version: the
scene graph (`services/api/app/services/scenes.py`, T-241). A version's
`provenance["scene"] = {"schema_version": 1, "nodes": [...]}` holds one node per object, each
owning its own `asset_id`, and several `model`-role `VersionAsset` rows already coexist on one
version by design (`versioning.py:123–132`; `scenes.py`'s `create_scene_version`,
`scenes.py:435–525`, attaches one per node). That is exactly the "several files, one version"
shape a bundle needs — built for a different feature (manual multi-object scene editing) and
otherwise unused by marketplace today.

`acquire()` changes to:

- Load `marketplace_item_components` for `item.id` (ordered by `sort_order`) alongside the
  anchor `source` version it already loads.
- `_copy_asset` each component's model asset into the buyer's `workspace_id` — the exact call
  already used for the anchor (`marketplace.py:403–434`), just applied in a loop over more
  sources instead of only `source.assets`.
- Build one scene node per bundle member — the anchor plus each component — each
  `{"id": ..., "kind": "object", "parent_id": None, "visible": True, "transform": IDENTITY,
  "asset_id": <copied asset id>, "instance_of": None}`, named from `item.title` for the anchor
  and `component.label` for each component. Attach every node's asset to the **one** new
  `ProjectVersion` via `projects.attach_asset(db, version, asset_id, AssetRole.model,
  workspace_id=workspace_id)` in a loop — the same call `create_scene_version` already makes per
  node (`scenes.py:511–515`); `IDENTITY` is the same 4×4 identity matrix constant
  (`scenes.py:25–30`).
- A listing with zero components (today's shape) produces exactly the scene it produces today:
  one node, one `model`-role asset — `_stored_nodes`'s own backward-compatibility fallback
  (`scenes.py:98–119`) already treats a single-model version as a one-node scene, so nothing
  about single-item acquisition changes.
- `project.head_version_id` still points at this one version — `acquire()` creates exactly one
  version per order, as today. The buyer's product-page viewer renders it the same way it
  already renders any other multi-node scene, because structurally it is one, not a new
  rendering path requiring new frontend work.
- Operations: the anchor's `Operation` rows are copied as today (`marketplace.py:510–527`);
  component versions' own operation histories are **not** copied — a component is delivered as
  a finished mesh node placed in the buyer's scene, not as an independently re-parametrizable
  history, matching what the mockups show (a window/yard module placed in the composition, not
  a separate editable project).

**Known limitation, named rather than silently accepted:** `assets.model_asset_of()`
(`services/assets.py:24–34`) returns the *first* `model`-role asset it finds for a version, with
no defined ordering — a pre-existing property of every scene-graph version, not something this
bundle delivery introduces. Any single-asset tool run against a bundle's acquired version (Fit
Test, print analysis, export) operates on an arbitrary one of its component meshes, not
necessarily the anchor. This is the same ambiguity that already exists today for any hand-built
multi-object scene; it is not new here, and fixing it (a defined node ordering for
`model_asset_of`, or making single-asset tools scene-node-aware) is a separate, pre-existing gap
outside this increment's scope.

### 3.3 Cart: `marketplace_cart_items`

```
marketplace_cart_items
  user_id       uuid FK -> users.id ON DELETE CASCADE
  workspace_id  uuid FK -> workspaces.id ON DELETE CASCADE
  item_id       uuid FK -> marketplace_items.id ON DELETE CASCADE
  added_at      timestamptz NOT NULL DEFAULT now()
  PRIMARY KEY (user_id, workspace_id, item_id)
```

- No separate "cart header" row. A user's cart for a workspace is simply every
  `marketplace_cart_items` row for that `(user_id, workspace_id)` pair — the same style the
  module already uses for `CreatorSubscription` (a following relation with no header row).
- `workspace_id` plays the same role here it plays in `AcquireBody.workspace_id` today: the
  destination the items will land in once paid for. Adding the same listing twice is a
  conflict-free no-op via the primary key, mirroring how `acquire()` already treats a repeat
  `(item_id, workspace_id)` as "already got it" rather than an error
  (`marketplace.py:455–463`).
- New service functions, all re-validating against **live** listing state (never trusting a
  stale cart row), and all starting with `require_workspace_role(db, user_id, workspace_id,
  WorkspaceRole.viewer)` — the same call `acquire()` already opens with
  (`marketplace.py:452`) — because `workspace_id` is now a value the client supplies on every
  one of these calls, not one the server derives: without this check, any authenticated user
  could add to or read the cart of a workspace they have no role in, just by passing its id.
  - `cart_add(db, *, user_id, workspace_id, item_id)` — rejects exactly like `acquire()` does
    today for the same two conditions: listing not published (`"this listing is not on offer"`,
    reusing `get_listing`'s visibility rule), or `item.workspace_id == workspace_id`
    (`"this listing already lives in that workspace"`, reusing `acquire()`'s existing message
    verbatim rather than inventing new wording for the same fact).
  - `cart_remove(db, *, user_id, workspace_id, item_id)`.
  - `cart_list(db, *, user_id, workspace_id) -> list[MarketplaceItem]`.
  - `cart_total_cents(db, *, user_id, workspace_id) -> int` — sums `price_cents` over the live
    listing rows (not a cached total), so a price change between add-to-cart and checkout is
    reflected honestly, not silently stale.
- **Which workspace's cart.** Every cart row is keyed by `(user_id, workspace_id, item_id)` and
  every function above takes `workspace_id` explicitly — there is no "current/default
  workspace" concept anywhere in this codebase to derive it from instead. `User`
  (`models/core.py`) has no such field, and every existing workspace-scoped endpoint resolves it
  the same explicit way: `AcquireBody.workspace_id` is a required POST body field
  (`api/marketplace.py:124–125`), `GET /projects` takes `workspace_id: uuid.UUID` as a required
  query parameter (`api/projects.py:229–233`), and `DELETE /printer-profiles/{id}/tuning` takes
  its scoping value the same way via `Query(...)` (`api/printing.py:524–529`). The cart
  endpoints follow this existing convention rather than inventing a new one:
  - `POST /cart/items {item_id, workspace_id}` — body field, same shape as `AcquireBody`.
  - `DELETE /cart/items/{item_id}?workspace_id=...` — required query parameter on the path
    endpoint, same shape as `reset_tuning`'s `material_id` query parameter.
  - `GET /cart?workspace_id=...` — required query parameter, same shape as `GET /projects`.

  (All three return/accept the same `ListingOut` shape §2/§3 already extended, so the cart
  screen reuses `ListingCard` as-is.)

### 3.4 Migration

One new alembic revision (next head after `0029_job_pause_resume.py`, i.e. `0030_...py`), two
`create_table` calls, no `alter_table` on any existing table. Fully additive and fully backward
compatible: every existing listing and order row is untouched, and the API response shape only
grows by two optional/empty fields (`components: []`, unaffected cart state).

### 3.5 What checkout will need later (explicitly not built now)

Once a payment provider is chosen, checkout has to decide between charging once for the whole
cart total (one `Charge`, many `MarketplaceOrder` rows sharing one `payment_reference`) or
charging per listing (many `Charge` calls, same semantics `acquire()` has today, just looped).
That is a `PaymentProvider` interface question (`payments.py:32–35`'s `charge()` takes one
amount, not a basket) entangled with whichever provider's API shape is chosen — correctly a
question for the provider-integration increment, not this one. This doc deliberately does not
pre-guess that answer; it only makes sure the cart/bundle schema above does not foreclose either
option (both a single combined charge and N individual charges can be built from
`cart_list()` + `cart_total_cents()` as given).

## 4. `commercial_use` enforcement (fail-closed)

### 4.1 Where the real risk is

`Licence.commercial_use` (`licensing.py:30`) is a property of the **licence**, not of the
project. Three situations pass silently through the code with no check at all — the third
found only once a naive fix for the second was implemented and exercised by a regression test,
and it is the one a careless version of §4.2 does not actually close:

- **Self-contradiction:** someone lists a listing for money (`price_cents > 0`) under a licence
  that says `commercial_use=False`. The licence text and the act of selling it directly
  contradict each other, and nothing stops it.
- **Laundering via remix lineage:** someone `acquire()`s a listing published under a
  non-commercial licence (say `CC-BY-NC-4.0`), and then — because `acquire()` sets
  `project.remixed_from_project_id = item.project_id` (`marketplace.py:636`) — later remixes
  that acquired project and republishes the remix under a *different*, commercial-friendly
  `license_id`. `licensing.chain()` (`licensing.py:151–163`) walks exactly this lineage already
  for other purposes, but nothing enforces it at `publish()`.
- **Laundering via the acquired project's own `license_id`** (the gap a naive chain-walk
  misses): `acquire()` sets `project.license_id = item.license_id` on the buyer's new project
  (`marketplace.py:634`) — the acquired copy's *own* licence is the non-commercial one. A
  chain-walk that checks only *ancestors* (`chain(db, project)[1:]`, deliberately skipping the
  project itself) never looks at that value at all. And a chain-walk that *does* include the
  project itself is still wrong if it trusts `project.license_id` there, because that field is
  editable at any time by any project editor via `set_license()` (`licensing.py:127–148`),
  which has — correctly — no restriction of its own (an author must stay free to loosen their
  *own* original work's terms). The two cases are indistinguishable by looking at
  `project.license_id` alone: a buyer can acquire a free `CC-BY-NC-4.0` listing, call
  `set_license(..., license_id="MIT")` on their own acquired copy (nothing stops this, by
  design — see §4.2), then publish it for a price under `MIT`. Every check that only reads
  `project.license_id` — for the chosen licence and for every project in the chain — now sees
  `MIT` where the buyer actually received a non-commercial term.

### 4.2 Enforcement point 1: listing a priced item

The fix is **not** "always include the project's own current `license_id` in the restriction
check" — that would also block a legitimate author from loosening their *own* original work's
licence (e.g. MIT → Apache-2.0 on a project they authored themselves, never acquired from
anyone), which `set_license()` exists to allow and must keep allowing. The two cases need
telling apart, and this codebase already has exactly the record needed to tell them apart: **a
project's own `license_id` is a received, buyer-immutable term when, and only when, that
project was produced by a marketplace acquisition — and a free choice otherwise.** The
authoritative source for "was this project acquired, and under what licence" is the
`MarketplaceOrder` row `acquire()` writes (`marketplace.py:740–752`), whose `item_id` points at
a `MarketplaceItem` whose `license_id` is fixed the moment `publish()` sets it —
`update_listing()` (`marketplace.py:368–`) has no `license_id` field to patch, it is
write-once. A project with no such order is organically authored; its own `license_id` stays
exactly as free to change as `set_license()` already treats it today.

New functions in `services/api/app/services/licensing.py`:

```python
def _acquired_licence(db: Session, project: Project) -> Licence | None:
    """The licence this project was actually acquired under, when it is a marketplace
    acquisition — read from the fixed, buyer-cannot-edit `MarketplaceItem.license_id` of the
    order that produced it, never from `project.license_id` (which `set_license()` lets any
    editor rewrite freely, by design, for an organic author's own work). None means this
    project carries no acquisition order — an organic project, with no externally imposed term
    to enforce here beyond its own freely-chosen licence."""
    order = db.scalar(
        sa.select(MarketplaceOrder).where(MarketplaceOrder.project_id == project.id)
    )
    if order is None:
        return None
    item = db.get(MarketplaceItem, order.item_id)
    assert item is not None
    return LICENCES.get(item.license_id, OWN_WORK)


def _enforced_licence_of(db: Session, project: Project) -> Licence:
    """The licence term that actually binds this project: its acquisition licence when it is
    an acquisition (buyer-immutable), otherwise its own current `license_id` — an organic
    author's free choice, unchanged from today's behaviour."""
    return _acquired_licence(db, project) or licence_of(project)


def assert_may_list_for_price(
    db: Session, project: Project, license_id: str, price_cents: int
) -> None:
    if price_cents <= 0:
        return
    chosen = LICENCES.get(license_id, OWN_WORK)
    if not chosen.commercial_use:
        raise ValidationFailedError("a non-commercial licence cannot be sold")
    for link in chain(db, project):  # the project itself first, then every true ancestor
        term = _enforced_licence_of(db, link)
        if not term.commercial_use:
            raise ValidationFailedError(
                "this work descends from a non-commercial listing; it cannot be sold",
                {"project_id": str(link.id), "licence_id": term.id},
            )
```

The change from the original pseudocode is two parts, and both are required: the loop walks
`chain(db, project)` in **full**, not `[1:]`, so the project's own slot is checked; and every
link's term is resolved through `_enforced_licence_of`, not `licence_of`, so that slot is
checked against the project's *acquisition* licence when it has one, never against its
freely-editable `license_id`. An organic project's own slot still resolves to
`licence_of(project)` exactly as before — no new restriction on legitimate self-relicensing.
An acquired project's own slot resolves to the listing's original, fixed licence regardless of
anything `set_license()` did to it afterward.

Called from `marketplace.publish()` / `publish_bundle()` and from `update_listing()`'s
`price_cents`-changing path, exactly as originally specified — this changes what the check
does, not where it is called.

This closes all three situations in §4.1 in one pass: a non-commercial licence can never be
sold by anyone; a commercial-use restriction propagates down true remix lineage; and an
acquired project's received non-commercial term survives any attempt to overwrite
`project.license_id` after the fact, because enforcement never trusts that field for an
acquisition in the first place — it goes straight to the order that produced it instead.

**`permissions()`/`remix()` need the identical substitution, or the hole reopens one step
later.** `licensing.permissions()` (`licensing.py:193–`) builds its `licences` list, its
`"licence"` display field, and its `credits` strings via `licence_of(p)` for every link,
including the project itself — and `remix()` (`licensing.py:240–`) trusts
`permissions()`'s derived flags to decide whether a further remix is allowed. Left as
`licence_of`, remixing an acquired project (one step past the direct republish §4.2 closes)
would reopen the identical hole one level deeper: `permissions()` would compute terms from the
acquired project's editable `license_id`, not what it was actually acquired under, and hand a
falsely-loosened term down to whatever remixes it next. Every one of those three call sites
must use `_enforced_licence_of(db, p)` in place of `licence_of(p)` — the same one-line
substitution, applied everywhere a project's licence feeds either an enforcement decision or a
term shown back to a user, not only at the two call sites named in §4.2/§4.3.

**Performance note:** `_acquired_licence` adds one `MarketplaceOrder` lookup per chain link
touched by `assert_may_list_for_price`, `assert_may_use_commercially`, and `permissions()`.
`MarketplaceOrder.project_id` has no index today — only `(item_id, workspace_id)` unique and
`(buyer_user_id, created_at)` exist (`models/marketplace.py:133–136`). Add
`Index("ix_marketplace_orders_project", "project_id")` in the same `0030` migration — additive,
no new column, no backfill.

**Known adjacent gap, not fixed here:** `derivatives`/`share_alike` are not enforced at
`publish()` either (e.g. a `CC-BY-ND` — No Derivatives — ancestor does not currently block
`publish()` of a derived version at all, commercial or free). That is a real, separate gap the
audit did not ask this increment to close; naming it here rather than silently leaving it
ambiguous.

### 4.3 Enforcement point 2: self-declared commercial export

`ExportCreate` (`api/exports.py:44`) gets one new field, `commercial: bool = False` — the same
self-declaration pattern `printable: bool` already uses on the same model. When `commercial is
True`, `create_export()` calls `licensing.assert_may_use_commercially()` before calling
`jobs.enqueue`, which must walk the chain through the same `_enforced_licence_of` helper as
§4.2 — not `licence_of` directly, for the identical reason: a buyer can call `set_license()` on
an acquired project before requesting a commercial export just as easily as before
republishing it, and the export gate must not be fooled by that either.

```python
def assert_may_use_commercially(db: Session, project: Project) -> None:
    for link in chain(db, project):
        term = _enforced_licence_of(db, link)
        if not term.commercial_use:
            raise ValidationFailedError(
                "this work descends from a non-commercial listing; commercial export is forbidden",
                {"project_id": str(link.id), "licence_id": term.id},
            )
```

**Honest limitation, stated plainly:** this only catches a user who truthfully marks their own
export as commercial. A dishonest `commercial=False` on a commercial export bypasses it — the
same class of limit `attribution_required` already has today (the system requires attribution
*text*, but does not verify the export is actually used that way downstream). This increment
does not oversell the gate as more than what the data model can actually support; a true
technical gate (e.g. watermarking, licensing-server callouts) is out of scope and not implied.

## 5. M08 — "Примерить в проекте" wiring

### 5.1 Pre-purchase question, resolved

**Fit Test genuinely requires ownership — not by convention, by the same workspace isolation
that protects every paid asset in the system.** `enqueue_fit_test` (`fit.py:61–67`) resolves
both versions through `projects.get_version`/`get_project`, each gated by
`require_workspace_role`, and then explicitly asserts `other.workspace_id ==
project.workspace_id`. A marketplace listing's version lives in the **creator's** workspace; a
buyer's project lives in the **buyer's** workspace — different by construction, which is
exactly why `acquire()`'s job is to copy the asset across that boundary in the first place.
Loosening Fit Test specifically to cross that boundary pre-purchase would let a buyer get an
exact mm collision/clearance readout against their own model — which, for a pure
fastener/adapter/bracket listing, can functionally substitute for owning the file — without
paying. So: **no mesh-accurate Fit Test before acquisition.** This is resolved, not hand-waved.

What ships pre-purchase instead is a **declared-dimension preview**: a plain numeric diff
between the listing's already-public `summary.size_mm` (computed today by `_summary()`,
`marketplace.py:200–210`, visible on every card) and a target size the buyer enters by hand (or,
when the buyer's own project is a facade with `FacadeOpening`s already defined, the buyer picks
one of their project's existing `width_mm`/`height_mm` openings as the target instead of typing
it). This is declared-number-vs-declared-number, not a mesh boolean — weaker than the mockup's
mm-exact overlap render, but honest about being weaker, and needs no purchase gate because it
reads nothing the card didn't already show.

### 5.2 Floor/facade-side targeting: dropped from this increment, not shipped as a cosmetic label

Making "2 этаж, Северный фасад" addressing real needs two different things, and only one of
them is a missing-data problem. The floor index is confirmed absent
(`docs/design/HOUSE-AUTOLAYOUT-LT-SHAPES.md §3`: "there is no floor index anywhere in
`FloorPlan`, `PlanRoom`, `PlanWall`, or `PlanOpening`") — that part was already resolved by not
inventing one. The other part is a wiring problem, not a data problem, and matters more:
whatever the buyer picks has to actually reach the Fit Test engine. It doesn't, and nothing in
this increment's other sections makes it reach it. `FitTestBody` (`api/fit.py:17–22`) and
`enqueue_fit_test` (`fit.py:48–56`) take only `version_a_id`, `version_b_id`, and a generic
`Placement` — `align`/`offset_mm`/`rotate_z_deg` (`fit.py:33–36`). There is no `FacadeSide`
field, no opening-id field, nothing a facade selector could write into. `FacadeSide`
(`engineering/facade.py:14`) exists only on `FacadeOpening` (`engineering/facade.py:26–31`), a
different model entirely, used by the house-plan generator — it has no connection to Fit Test or
to `Placement` anywhere in the codebase.

A "Фасад: Передний/Задний/Левый/Правый" dropdown on the product page would therefore have
nothing to write to: selecting a value could not change `Placement`, could not restrict which
opening Fit Test targets, and could not change the job's outcome in any way — a real-looking UI
control with zero backend effect, which is worse than omitting it, because it implies a
precision the system does not have. So **this increment ships no facade-side selector at
all** — not a disabled one, not a decorative one. §5.3's wiring below needs no such field and
adds none. Making floor/facade targeting real needs `FitTestBody` to gain a target-opening
reference and `fit.py`'s worker to resolve and apply it before any such UI could mean anything —
that is real, multi-file backend work (API contract, job input, worker logic), and it is
explicitly **deferred to a future increment**, named here so it is not silently dropped, exactly
alongside the floor-index work `HOUSE-AUTOLAYOUT-LT-SHAPES.md §3` already defers.

### 5.3 Wiring

The product page (`market/[id]/page.tsx`) gets a new section, visible for every listing with a
mesh asset:

- **Not yet acquired:** shows the §5.1 declared-dimension preview, plus a line making the limit
  explicit ("Точная проверка доступна после покупки") and the existing acquire button as the
  CTA — no dead-end, no silent omission of the mockup's promise.
- **Already acquired** (a `MarketplaceOrder` exists for this `item_id` in one of the buyer's
  workspaces — checked the same way `acquire()` already checks for an existing order,
  `marketplace.py:455–459`): the section becomes the real Fit Test, rendering the **existing**
  `FitTestCard.tsx` component unmodified in its logic, pre-filled so the acquired copy's version
  is `version_b_id` and the buyer picks which of their *other* projects (in the same workspace)
  is `version_a_id` — i.e. the exact flow `FitTestCard` already offers from a project page
  (`apps/web/src/app/projects/[id]/page.tsx`), just launched from the listing page instead of
  requiring the buyer to navigate to a project and hunt for the acquired copy manually.
  `FitTestCard` needs one small addition: an optional `defaultOtherId` prop so the listing page
  can pre-select the acquired copy's sibling project without the user re-picking it from a list
  they already came from. No new backend endpoint — `POST /fit-tests` already accepts any two
  same-workspace versions.

## 6. UI/UX pass (M01–M04), scoped to visuals only

These screens' underlying data and endpoints are **not** changed by this section — only layout,
density, and a small number of additive display fields already designed above.

- **M01 (browse):** restyle the shelf grid toward the mockup's density; add a quick
  "В корзину" action directly on `ListingCard` using §3.3's `cart_add` (closing the audit's
  specific complaint that the only add-path today requires opening the product page first).
  Category *labels* stay the existing five (`print/game/arvr/cad/other`) — the mockup's
  shape-based taxonomy (Фигуры/Дома/Дворы) is a category-tree change, explicitly deferred (§1).
- **M02 (categories):** add a grid/list view toggle (`market/page.tsx:204` is hardcoded to
  `grid` today; both are trivial CSS-class swaps over the same data) and keep the existing flat
  category chips. The nested tree with per-subcategory counts stays deferred (§1) — this screen
  does not pretend to have it.
- **M03 (search/filters):** add a visible results count (the list length already returned by
  `search()`, just not currently rendered) to close the cheapest specific gap the audit names.
  `free_only`, `category`, and the three `sort` values are real today and get restyled, not
  reimplemented. Price-range slider, file-format filter, and the "редактируемый/2D-план/печать"
  toggles stay deferred — `MarketplaceItem` has no file-format field and no such boolean columns
  to filter on, and inventing three new filterable columns is a data-model change this doc does
  not bundle into a "visual pass."
- **M04 (product page):** wire `ModelViewer`'s existing `wireframe` prop
  (`ModelViewer.tsx:356`) into an Осмотр/Каркас view toggle on the listing page — the component
  already supports it, `market/[id]/page.tsx` just never passed it through. Add the §2 print
  badge, the §5 Fit Test section, and the creator's follower count (already computed by
  `CreatorPageOut`, just not fetched from this page today). Add a plain-language
  Личное/Коммерческое chip derived from `licence.commercial_use` next to the existing CC
  licence-name chip — pure display of a fact the model already has, not new enforcement (§4 is
  the enforcement; this is just making the fact visible, which doubles as the data M09's cart
  screen needs for its own Личное/Коммерческое badges). One format per listing stays as today —
  the STL/3MF *choice* UI stays deferred (§1) because there is only ever one file to choose from.

## 7. Touch list

**Backend:**
- `services/api/app/models/marketplace.py` — add `MarketplaceItemComponent`,
  `MarketplaceCartItem`.
- `services/api/app/services/marketplace.py` — `publish_bundle()` (subsumes `publish()`),
  `cart_add/remove/list/total_cents`, call `licensing.assert_may_list_for_price` from
  publish/patch price paths; `acquire()` changed per §3.2.1 to copy every
  `marketplace_item_components` row's asset into the buyer's workspace and compose them with
  the anchor into one multi-node `provenance["scene"]`, not just the anchor's asset.
- `services/api/app/services/licensing.py` — `assert_may_list_for_price()`.
- `services/api/app/services/printing.py` — `latest_analyses_for()` batch loader.
- `services/api/app/api/marketplace.py` — `ListingOut.components`/`print_verified`; batch-load
  print badges in every list endpoint; `POST /cart/items {item_id, workspace_id}`,
  `DELETE /cart/items/{item_id}?workspace_id=...`, `GET /cart?workspace_id=...` (§3.3).
- `services/api/app/api/exports.py` — `ExportCreate.commercial`; lineage check before enqueue.
- `services/api/alembic/versions/0030_*.py` — the two new tables, additive only.

**Frontend:**
- `apps/web/src/components/ListingCard.tsx` — print badge, bundle indicator, quick
  "В корзину" action.
- `apps/web/src/app/market/page.tsx` — grid/list toggle, results count.
- `apps/web/src/app/market/[id]/page.tsx` — viewer tabs, print badge, bundle contents list,
  Личное/Коммерческое chip, Fit Test section (§5.3), acquired-state detection.
- `apps/web/src/components/FitTestCard.tsx` — `defaultOtherId` prop.
- `apps/web/src/components/PublishCard.tsx` — optional component-adding step for bundle
  publish (secondary; a single-file publish must keep working exactly as today if this step is
  skipped).
- New `apps/web/src/app/cart/page.tsx` (or a drawer) — lists cart items via `GET /cart`, shows
  total, remove action; checkout button explicitly disabled/"скоро" — not wired to anything,
  per §3.5.
- `packages/contracts/src/api.d.ts` regenerates from the updated OpenAPI schema;
  `packages/contracts/src/client.ts` gains `addToCart`/`removeFromCart`/`getCart` methods
  alongside the existing `publishListing`/`startFitTest`.

## 8. Fail-closed boundary

| Case | Outcome |
|---|---|
| Listing published/re-priced with `price_cents > 0` under a licence with `commercial_use=False` | **Rejected**: `"a non-commercial licence cannot be sold"` |
| Listing published/re-priced with `price_cents > 0`, descended (via `remixed_from_project_id` chain) from any ancestor licensed `commercial_use=False` | **Rejected**: `"this work descends from a non-commercial listing; it cannot be sold"` |
| Listing published/re-priced with `price_cents > 0` on a project that **is itself a marketplace acquisition** of a `commercial_use=False` listing — including after the buyer calls `set_license()` to relabel that acquired project under a commercial-friendly licence first | **Rejected**: `"this work descends from a non-commercial listing; it cannot be sold"` — the acquisition's original licence is read from the immutable `MarketplaceOrder`/`MarketplaceItem` record, not from the editable `project.license_id` (§4.2 laundering case) |
| Same project, but organically authored (no `MarketplaceOrder` points at it) and `set_license()` is used to loosen its own licence (e.g. `MIT` → `Apache-2.0`) before listing for a price | **Allowed** — no acquisition order exists, so nothing is enforced beyond the author's own freely-chosen licence; self-relicensing one's own original work is not restricted |
| Export with `commercial=True` declared, lineage includes a `commercial_use=False` ancestor | **Rejected** — export job never enqueued |
| `publish_bundle` with a component version not finalized, with no assets, or belonging to a different project than the anchor | **Rejected** — same per-version messages `publish()` already raises, applied per component |
| `publish_bundle` with a component `version_id` equal to the anchor's own `version_id`, or repeated within the same bundle | **Rejected**: duplicate component |
| `cart_add` for a listing that is not published (withdrawn/blocked/draft) | **Rejected**: `"this listing is not on offer"` (reusing `get_listing`'s existing visibility rule) |
| `cart_add` where `item.workspace_id == workspace_id` | **Rejected**: `"this listing already lives in that workspace"` (reusing `acquire()`'s exact existing message) |
| Any `cart_add`/`cart_remove`/`cart_list`/`cart_total_cents` call where the caller has no role in the supplied `workspace_id` | **Rejected** by `require_workspace_role`, the same gate every other workspace-scoped endpoint uses |
| Fit Test requested against an unacquired listing's version from a different workspace | **Not offered in the UI**; the existing `fit.py:66–67` same-workspace assertion is unchanged and still the real backstop |
| Print badge render when the latest analysis status is `yellow` or `red` | **Never renders the checkmark/"Проверено" claim** — shows the honest status chip, or nothing if no analysis exists at all |

No case above receives an approximated or "probably fine" result — every rejection names the
specific reason, matching the discipline already used in `licensing.py`/`entitlements.py`
(`SubscriptionRequiredError`, `ValidationFailedError` with structured detail).

## 9. Test plan

- **Licence enforcement (new, in `test_marketplace_api.py` or a sibling):**
  - Publishing a `price_cents > 0` listing under `CC-BY-NC-4.0` → `ValidationFailedError`.
  - Publishing a free (`price_cents == 0`) listing under `CC-BY-NC-4.0` → succeeds (the
    restriction is on *selling*, not on listing for free).
  - Acquire a `CC-BY-NC-4.0` listing, then try to publish a priced listing of (a version
    descended from) that acquired project → `ValidationFailedError` naming the ancestor.
  - Raising the price of an already-published non-commercial-descended listing via
    `patch_listing` → same rejection (closes the "one-time check" loophole).
  - **Laundering regression, named explicitly:** publish a free (`price_cents == 0`) listing
    under `CC-BY-NC-4.0` → acquire it into a second workspace → call `set_license()` on the
    *acquired* project to relabel it `MIT` → attempt to publish that acquired project for a
    price under `MIT` → must still raise `ValidationFailedError` naming the non-commercial
    acquisition, not succeed with `201`. This is the exact scenario a chain-walk that skips the
    project's own slot, or that trusts `project.license_id` for an acquisition, lets through —
    assert it is blocked specifically, not just the ancestor case above.
  - Companion case, same shape, opposite expected outcome: an **organically authored** project
    (never acquired — no `MarketplaceOrder` points at it), originally `MIT`, has its licence
    loosened further via `set_license()` and is then listed for a price → **succeeds**. Pairing
    this with the laundering regression proves the fix tells the two cases apart instead of
    either always blocking self-relicensing or never catching the laundering path.
  - Remix an acquired `CC-BY-NC-4.0` project, then try to publish the *remix* for a price under
    a commercial-friendly licence → `ValidationFailedError` — proves `permissions()`/`remix()`
    resolve the acquired ancestor's enforced licence too, not just `assert_may_list_for_price`'s
    own direct target.
  - `ExportCreate(commercial=True)` on a project descended from a non-commercial acquisition →
    rejected before `jobs.enqueue` is called; `commercial=False` on the same project → allowed
    (documenting the honest self-declaration limit from §4.3). Repeat with `set_license()`
    relabeling applied first, same as the laundering regression above → still rejected.
- **Print badge:**
  - A version with a `green` `PrintAnalysisRecord` → listing's `print_verified.status ==
    "green"`, card renders the checkmark.
  - A version with only a `red` record → `print_verified.status == "red"`, no checkmark
    rendered.
  - A version with no record → `print_verified is None`.
  - `search()` returning 30 listings triggers exactly one batched analysis query, not 30 (assert
    query count, the same style existing N+1 regression tests in this codebase use).
- **Bundles:**
  - `publish_bundle` with 3 valid sibling versions → `ListingOut.components` has 3 entries in
    `sort_order`; each has its own `summary`/`print_verified`.
  - A component version belonging to a different project than the anchor → rejected.
  - A component repeating the anchor's own `version_id` → rejected.
  - The same version used as a component in two different bundles → both succeed (no
    cross-bundle uniqueness).
  - A listing published via the old one-version `publish()` path still round-trips with
    `components == []` — proving zero regression for every pre-existing listing.
  - `acquire()` on a 3-component bundle copies all 4 model assets (anchor + 3) into the buyer's
    workspace and produces exactly one `ProjectVersion` whose `provenance["scene"]["nodes"]`
    has 4 entries, each with its own distinct copied `asset_id` — not just the anchor's, and
    each attached as a `model`-role `VersionAsset` on that one version (§3.2.1).
  - `acquire()` on a zero-component listing still produces the same single-node scene it
    produces today — proving zero regression for every pre-existing (non-bundle) listing.
  - Re-acquiring the same bundle order a second time (the existing `already is not None`
    short-circuit, `marketplace.py:455–463`) returns the existing project and does not
    re-copy components or duplicate scene nodes.
- **Cart (every call below passes `workspace_id` explicitly, per §3.3):**
  - `cart_add` then `cart_list` round-trips the listing for that `(user_id, workspace_id)` pair;
    `cart_total_cents` sums correctly across 2+ items.
  - `cart_add` twice for the same `(item_id, workspace_id)` is a no-op (no duplicate row, no
    error).
  - `cart_add` for a withdrawn listing → rejected with the reused message.
  - `cart_add` where `item.workspace_id == workspace_id` → rejected with the reused message.
  - `cart_list`/`cart_add`/`cart_remove` called with a `workspace_id` the user has no role in →
    rejected the same way every other workspace-scoped endpoint rejects it
    (`require_workspace_role`).
  - `cart_remove` then `cart_list` no longer includes it.
  - A price change on a cart-held listing between add and a later `cart_total_cents` call is
    reflected live, not stale (no caching bug).
- **M08 wiring:**
  - Listing page for an unacquired item never calls `POST /fit-tests` — only renders the
    declared-dimension diff from already-public `summary.size_mm` plus a user-entered/opening
    target.
  - After `acquire()`, the same page's Fit Test section pre-fills `version_b_id` to the
    acquired copy and lets `version_a_id` be chosen from the buyer's other same-workspace
    projects — an integration test asserting the pre-fill, not just the existing
    `test_fit_api.py` coverage of the endpoint itself (which is unchanged).
- **Ledger gate:** full API test suite (690 passed/3 skipped baseline per
  `docs/IMPLEMENTED.md`) plus Ruff/mypy, plus `packages/contracts` typecheck and `apps/web`
  production build, same bar as every other shipped increment in this ledger.

## Summary

- **Print badge:** one batched join (`latest_analyses_for`), shown only when the analysis is
  genuinely `green` — the cheapest real fix, exactly as the audit doc already flagged.
- **Cart/bundle schema:** two new additive tables (`marketplace_item_components`,
  `marketplace_cart_items`), zero changes to existing tables, zero regression for any listing
  that exists today — checkout itself stays unbuilt, deliberately, pending the provider
  decision (§3.5). `workspace_id` is explicit on every cart endpoint and re-authorized on every
  cart call (§3.3) — this codebase has no "current workspace" concept to fall back on, so the
  cart follows the same explicit-and-authorized pattern every other workspace-scoped endpoint
  already uses.
- **Bundle delivery:** `acquire()` now copies every component's asset into the buyer's
  workspace too, not just the anchor's, composing them into one multi-node scene version by
  reusing the existing scene-graph mechanism (`scenes.py`, §3.2.1) — no new schema, no new
  rendering path, and zero-component listings produce exactly the version they produce today.
- **`commercial_use` enforcement:** two new licensing helpers (`_acquired_licence`,
  `_enforced_licence_of`), applied at every point a project's licence is read for enforcement
  or shown back to a user — `assert_may_list_for_price`, `assert_may_use_commercially`, and
  `permissions()` — closing the self-contradiction case, the remix-lineage laundering case,
  *and* the acquired-project's-own-`license_id` laundering case a naive chain-walk misses
  (confirmed exploitable: acquire a free non-commercial listing, `set_license()` the acquired
  copy to something commercial-friendly, republish for a price — now rejected, because
  enforcement reads the immutable acquisition order, not the editable `project.license_id`).
  Legitimate self-relicensing of one's own organic work is unaffected — with the adjacent
  `derivatives`/`share_alike` gap named, not silently left ambiguous.
- **M08:** resolved, not hand-waved — pre-purchase gets a declared-dimension preview because
  mesh-accurate Fit Test genuinely requires crossing the same workspace boundary every other
  paid asset is protected by; post-purchase gets the real, unmodified Fit Test engine. No
  facade-side selector ships in this increment at all — `FitTestBody`/`Placement` have nowhere
  for such a value to go, so a selector with no backend effect is not built; floor/facade
  targeting is deferred as real backend work, alongside the floor-index work already named in
  `HOUSE-AUTOLAYOUT-LT-SHAPES.md`.
- **M01–M04:** a real UI/UX pass on working screens — grid/list toggle, results count, viewer
  tabs, licence-term chip — with the category-tree and multi-format-file gaps named as
  data-model work this is not.
- **Explicitly deferred:** payment provider + checkout, category tree, multi-format listings,
  document exports (PDF/DWG/XLSX), yard composition/autotour, publish moderation queue, floor
  index/compass.
