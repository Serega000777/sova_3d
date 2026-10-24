"""Marketplace (T-148/F-004), creator collections (F-065), fit search (F-046).

Publishing puts a finalized version on the shelf under a licence. Acquiring copies that
version — assets and parametric history — into the buyer's workspace with the credit
written, so what the buyer got is an ordinary project that remembers where it came from.
Following a creator is a subscription; their new listings are the feed.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.config import Settings
from app.engineering.facade import FacadeRequest, opening_key
from app.engineering.floor_plan import BuildingFloorPlans, FloorPlan
from app.engineering.house_box import HouseBoxRequest
from app.models.core import Project, User, WorkspaceRole
from app.models.execution import Job, JobStatus, Operation
from app.models.marketplace import (
    CreatorCollection,
    CreatorCollectionItem,
    CreatorProfile,
    CreatorSubscription,
    ListingCategory,
    ListingDomain,
    ListingStatus,
    MarketplaceCartItem,
    MarketplaceFavorite,
    MarketplaceItem,
    MarketplaceItemComponent,
    MarketplaceOrder,
    OrderStatus,
)
from app.models.printing import AnalysisKind, PrintAnalysisRecord
from app.models.versioning import Asset, AssetRole, ProjectVersion, VersionAsset, VersionState
from app.services import licensing, projects
from app.services.asset_copies import copy_asset_to_workspace
from app.services.authz import require_workspace_role
from app.storage import ObjectStorage

HANDLE = re.compile(r"^[a-z0-9][a-z0-9-]{2,31}$")
SUBCATEGORY = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_TAGS = 12
SEARCH_LIMIT = 100
MARKETPLACE_TAXONOMY: dict[str, dict[str, Any]] = {
    "figure": {
        "label_en": "Figures",
        "label_ru": "Фигуры",
        "subcategories": (
            ("people", "People", "Люди"),
            ("animals", "Animals", "Животные"),
            ("vehicles", "Vehicles", "Транспорт"),
            ("home-decor", "Home decor", "Декор для дома"),
        ),
    },
    "element": {
        "label_en": "Elements",
        "label_ru": "Элементы",
        "subcategories": (
            ("facade", "Facade elements", "Фасадные элементы"),
            ("doors-windows", "Doors and windows", "Двери и окна"),
            ("roofing", "Roofing", "Кровля"),
            ("stairs-railings", "Stairs and railings", "Лестницы и ограждения"),
            ("home-decor", "Home decor", "Декор для дома"),
        ),
    },
    "house": {
        "label_en": "Houses",
        "label_ru": "Дома",
        "subcategories": (
            ("residential", "Residential houses", "Жилые дома"),
            ("garden-house", "Garden houses", "Садовые дома"),
            ("garage", "Garages", "Гаражи"),
            ("modular", "Modular houses", "Модульные дома"),
        ),
    },
    "yard": {
        "label_en": "Yards",
        "label_ru": "Дворы",
        "subcategories": (
            ("landscaping", "Landscaping", "Ландшафт"),
            ("fences-gates", "Fences and gates", "Заборы и ворота"),
            ("outdoor-furniture", "Outdoor furniture", "Уличная мебель"),
            ("playgrounds", "Playgrounds", "Игровые площадки"),
        ),
    },
    "printable": {
        "label_en": "For printing",
        "label_ru": "Для печати",
        "subcategories": (
            ("organizers", "Organizers", "Органайзеры"),
            ("cable-management", "Cable management", "Крепления для кабелей"),
            ("wall-mounts", "Wall mounts", "Настенные крепления"),
            ("tools", "Tools", "Инструменты"),
            ("replacement-parts", "Replacement parts", "Запасные детали"),
        ),
    },
    "other": {
        "label_en": "Other",
        "label_ru": "Другое",
        "subcategories": (
            ("education", "Education", "Образование"),
            ("art", "Art", "Искусство"),
            ("electronics", "Electronics", "Электроника"),
            ("misc", "Miscellaneous", "Разное"),
        ),
    },
}


@dataclass(frozen=True)
class DeliveredMarketplaceFile:
    asset: Asset
    role: AssetRole
    labels: tuple[str, ...]


FACADE_SIZE_TOLERANCE_MM = 1.0
HOUSE_BOX_JOB = "build_house_box"
FACADE_JOB = "edit_facade"


@dataclass(frozen=True)
class FacadeCompatibility:
    project: Project
    version: ProjectVersion | None
    status: str
    reason: str | None
    openings: tuple[dict[str, Any], ...]
    matched_openings: int


@dataclass(frozen=True)
class MarketplaceHouseMetadata:
    length_mm: float
    width_mm: float
    floors: int
    gross_floor_area_m2: float
    source: str


CONFIGURABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "create_box": ("width_mm", "depth_mm", "height_mm"),
    "create_hip_roof": ("width_mm", "depth_mm", "height_mm"),
    "create_cylinder": ("diameter_mm", "height_mm"),
    "create_sphere": ("diameter_mm",),
    "create_cone": ("bottom_diameter_mm", "top_diameter_mm", "height_mm"),
    "create_torus": ("outer_diameter_mm", "tube_diameter_mm"),
    "extrude": ("height_mm",),
    "revolve": ("angle_deg",),
}

# --- creators ---------------------------------------------------------------------------------


def slugify_handle(text: str) -> str:
    """A handle out of an email's local part or a display name — never empty, never long."""
    handle = re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")[:32]
    if len(handle) < 3:
        handle = (handle + "-maker")[:32]
    return handle


def normalize_taxonomy_pair(domain: str, subcategory: str | None) -> tuple[str, str | None]:
    """Validate a listing against the ordered, server-owned editorial taxonomy."""
    taxonomy = MARKETPLACE_TAXONOMY.get(domain)
    if taxonomy is None:
        raise ValidationFailedError(
            "unknown marketplace domain", {"known": list(MARKETPLACE_TAXONOMY)}
        )
    clean_subcategory = (subcategory or "").strip().lower() or None
    if clean_subcategory is None:
        return domain, None
    known = [row[0] for row in taxonomy["subcategories"]]
    if not SUBCATEGORY.fullmatch(clean_subcategory) or clean_subcategory not in known:
        raise ValidationFailedError(
            "subcategory does not belong to this marketplace domain",
            {"domain": domain, "subcategory": subcategory, "known": known},
        )
    return domain, clean_subcategory


def has_2d_plan_evidence(provenance: dict[str, Any] | None) -> bool:
    """Accept only a schema-valid, non-empty versioned plan as marketplace evidence."""
    raw = provenance or {}
    try:
        if isinstance(raw.get("floor_plan"), dict):
            plan = FloorPlan.model_validate(raw["floor_plan"])
            return bool(plan.walls or plan.rooms)
        if isinstance(raw.get("floor_plans"), dict):
            building = BuildingFloorPlans.model_validate(raw["floor_plans"])
            return any(level.plan.walls or level.plan.rooms for level in building.levels)
    except ValidationError:
        return False
    return False


def house_metadata_for_versions(
    db: Session, version_ids: list[uuid.UUID]
) -> dict[uuid.UUID, MarketplaceHouseMetadata]:
    """Return only house facts reproduced from the successful job that made each version."""
    if not version_ids:
        return {}
    wanted = {str(version_id): version_id for version_id in version_ids}
    rows = db.scalars(
        sa.select(Job)
        .where(
            Job.type.in_((HOUSE_BOX_JOB, FACADE_JOB)),
            Job.status == JobStatus.succeeded,
            Job.result["version_id"].astext.in_(wanted),
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
    ).all()
    output: dict[uuid.UUID, MarketplaceHouseMetadata] = {}
    for job in rows:
        result_version_id = (job.result or {}).get("version_id")
        if not isinstance(result_version_id, str) or result_version_id not in wanted:
            continue
        version_id = wanted[result_version_id]
        if version_id in output:
            continue
        try:
            if job.type == HOUSE_BOX_JOB:
                request = HouseBoxRequest(**dict(job.input.get("request") or {}))
                if request.shape != "rectangle":
                    continue
                source = "house_box"
            else:
                facade = FacadeRequest(**dict(job.input.get("request") or {}))
                request = HouseBoxRequest(
                    length_mm=facade.length_mm,
                    width_mm=facade.width_mm,
                    floor_height_mm=facade.floor_height_mm,
                    floors=facade.floors,
                    shape="rectangle",
                )
                source = "facade"
        except (TypeError, ValueError, ValidationError):
            continue
        output[version_id] = MarketplaceHouseMetadata(
            length_mm=float(request.length_mm),
            width_mm=float(request.width_mm),
            floors=int(request.floors),
            gross_floor_area_m2=round(
                float(request.length_mm)
                * float(request.width_mm)
                * int(request.floors)
                / 1_000_000,
                3,
            ),
            source=source,
        )
    return output


def profile_of(db: Session, user_id: uuid.UUID) -> CreatorProfile | None:
    return db.get(CreatorProfile, user_id)


def profile_by_handle(db: Session, handle: str) -> CreatorProfile:
    profile = db.scalar(sa.select(CreatorProfile).where(CreatorProfile.handle == handle.lower()))
    if profile is None:
        raise NotFoundError("creator", handle)
    return profile


def ensure_profile(db: Session, user_id: uuid.UUID) -> CreatorProfile:
    """The user's creator profile, made from their account when they never wrote one."""
    profile = profile_of(db, user_id)
    if profile is not None:
        return profile
    user = db.get(User, user_id)
    assert user is not None
    base = slugify_handle(user.display_name or (user.email or "maker").split("@")[0])
    handle, n = base, 1
    while db.scalar(sa.select(CreatorProfile).where(CreatorProfile.handle == handle)) is not None:
        n += 1
        handle = f"{base[: 32 - len(str(n)) - 1]}-{n}"
    profile = CreatorProfile(
        user_id=user_id,
        handle=handle,
        display_name=(user.display_name or (user.email or "maker").split("@")[0])[:100],
    )
    db.add(profile)
    db.flush()
    return profile


def upsert_profile(
    db: Session,
    *,
    user_id: uuid.UUID,
    handle: str | None,
    display_name: str | None,
    bio: str | None,
    website: str | None,
) -> CreatorProfile:
    profile = ensure_profile(db, user_id)
    if handle is not None:
        wanted = handle.lower().strip()
        if not HANDLE.match(wanted):
            raise ValidationFailedError(
                "a handle is 3–32 lowercase letters, digits or dashes", {"handle": handle}
            )
        taken = db.scalar(
            sa.select(CreatorProfile).where(
                CreatorProfile.handle == wanted, CreatorProfile.user_id != user_id
            )
        )
        if taken is not None:
            raise ConflictError("that handle is taken", {"handle": wanted})
        profile.handle = wanted
    if display_name is not None:
        if not display_name.strip():
            raise ValidationFailedError("display_name must not be empty")
        profile.display_name = display_name.strip()[:100]
    if bio is not None:
        profile.bio = bio.strip()[:2000] or None
    if website is not None:
        profile.website = website.strip()[:500] or None
    db.flush()
    return profile


def follow(db: Session, *, follower_id: uuid.UUID, handle: str) -> CreatorProfile:
    creator = profile_by_handle(db, handle)
    if creator.user_id == follower_id:
        raise ValidationFailedError("you cannot follow yourself")
    existing = db.get(CreatorSubscription, (follower_id, creator.user_id))
    if existing is None:
        db.add(CreatorSubscription(follower_user_id=follower_id, creator_user_id=creator.user_id))
        db.flush()
    return creator


def unfollow(db: Session, *, follower_id: uuid.UUID, handle: str) -> CreatorProfile:
    creator = profile_by_handle(db, handle)
    existing = db.get(CreatorSubscription, (follower_id, creator.user_id))
    if existing is not None:
        db.delete(existing)
        db.flush()
    return creator


def is_following(db: Session, *, follower_id: uuid.UUID, creator_user_id: uuid.UUID) -> bool:
    return db.get(CreatorSubscription, (follower_id, creator_user_id)) is not None


def followers_count(db: Session, creator_user_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            sa.select(sa.func.count())
            .select_from(CreatorSubscription)
            .where(CreatorSubscription.creator_user_id == creator_user_id)
        )
        or 0
    )


def following(db: Session, follower_id: uuid.UUID) -> list[CreatorProfile]:
    return list(
        db.scalars(
            sa.select(CreatorProfile)
            .join(
                CreatorSubscription, CreatorSubscription.creator_user_id == CreatorProfile.user_id
            )
            .where(CreatorSubscription.follower_user_id == follower_id)
            .order_by(CreatorProfile.handle)
        )
    )


def feed(db: Session, follower_id: uuid.UUID, *, limit: int = 50) -> list[MarketplaceItem]:
    """The newest listings of the creators the user follows."""
    return list(
        db.scalars(
            sa.select(MarketplaceItem)
            .join(
                CreatorSubscription,
                CreatorSubscription.creator_user_id == MarketplaceItem.creator_user_id,
            )
            .where(
                CreatorSubscription.follower_user_id == follower_id,
                MarketplaceItem.status == ListingStatus.published.value,
            )
            .order_by(MarketplaceItem.published_at.desc(), MarketplaceItem.id)
            .limit(limit)
        )
    )


def creator_collections(db: Session, creator_user_id: uuid.UUID) -> list[CreatorCollection]:
    return list(
        db.scalars(
            sa.select(CreatorCollection)
            .where(CreatorCollection.creator_user_id == creator_user_id)
            .order_by(CreatorCollection.created_at, CreatorCollection.id)
        )
    )


def collection_items(db: Session, collection_id: uuid.UUID) -> list[MarketplaceItem]:
    return list(
        db.scalars(
            sa.select(MarketplaceItem)
            .join(CreatorCollectionItem, CreatorCollectionItem.item_id == MarketplaceItem.id)
            .where(
                CreatorCollectionItem.collection_id == collection_id,
                MarketplaceItem.status == ListingStatus.published.value,
            )
            .order_by(CreatorCollectionItem.sort_order)
        )
    )


def _owned_collection(
    db: Session, *, creator_user_id: uuid.UUID, collection_id: uuid.UUID
) -> CreatorCollection:
    collection = db.get(CreatorCollection, collection_id)
    if collection is None or collection.creator_user_id != creator_user_id:
        raise NotFoundError("creator collection", collection_id)
    return collection


def save_collection(
    db: Session,
    *,
    creator_user_id: uuid.UUID,
    collection_id: uuid.UUID | None,
    title: str,
    description: str | None,
    item_ids: list[uuid.UUID],
) -> CreatorCollection:
    """Create/update one collection, accepting only this creator's published listings."""
    # Resolve ownership before validating mutable fields. Otherwise a stranger could learn that
    # a collection id exists from a 422 response instead of the resource-obscuring 404 contract.
    collection = (
        _owned_collection(db, creator_user_id=creator_user_id, collection_id=collection_id)
        if collection_id is not None
        else None
    )
    clean_title = re.sub(r"\s+", " ", title.strip())
    if not clean_title:
        raise ValidationFailedError("collection title must not be empty")
    if len(set(item_ids)) != len(item_ids):
        raise ValidationFailedError("collection contains duplicate listings")
    items = list(db.scalars(sa.select(MarketplaceItem).where(MarketplaceItem.id.in_(item_ids))))
    by_id = {item.id: item for item in items}
    if len(by_id) != len(item_ids) or any(
        by_id[item_id].creator_user_id != creator_user_id
        or by_id[item_id].status != ListingStatus.published.value
        for item_id in item_ids
    ):
        raise ValidationFailedError("collections may contain only your published listings")
    collection = collection or CreatorCollection(creator_user_id=creator_user_id, title=clean_title)
    collection.title = clean_title[:120]
    collection.description = (description or "").strip()[:1000] or None
    db.add(collection)
    db.flush()
    db.execute(
        sa.delete(CreatorCollectionItem).where(CreatorCollectionItem.collection_id == collection.id)
    )
    for index, item_id in enumerate(item_ids):
        db.add(
            CreatorCollectionItem(collection_id=collection.id, item_id=item_id, sort_order=index)
        )
    db.flush()
    return collection


def delete_collection(db: Session, *, creator_user_id: uuid.UUID, collection_id: uuid.UUID) -> None:
    collection = _owned_collection(db, creator_user_id=creator_user_id, collection_id=collection_id)
    db.delete(collection)
    db.flush()


def creator_insights(db: Session, creator_user_id: uuid.UUID) -> dict[str, Any]:
    """Observed marketplace demand and creator performance over two rolling 30-day windows."""
    now = datetime.now(UTC)
    current_start = now - timedelta(days=30)
    previous_start = current_start - timedelta(days=30)
    rows = db.execute(
        sa.select(MarketplaceOrder, MarketplaceItem)
        .join(MarketplaceItem, MarketplaceItem.id == MarketplaceOrder.item_id)
        .where(
            MarketplaceOrder.status == OrderStatus.completed.value,
            MarketplaceOrder.created_at >= previous_start,
        )
    ).all()
    categories: dict[str, dict[str, int]] = {}
    for order, item in rows:
        bucket = categories.setdefault(item.category, {"recent": 0, "previous": 0})
        bucket["recent" if order.created_at >= current_start else "previous"] += 1
    demand: list[dict[str, Any]] = []
    for category, counts in categories.items():
        previous = counts["previous"]
        change_pct = round((counts["recent"] - previous) / previous * 100, 1) if previous else None
        demand.append(
            {
                "category": category,
                "recent_orders": counts["recent"],
                "previous_orders": previous,
                "change_pct": change_pct,
            }
        )
    demand.sort(key=lambda row: (-row["recent_orders"], row["category"]))

    owned = my_listings(db, creator_user_id)
    order_totals = {
        item_id: (int(count), int(gross or 0))
        for item_id, count, gross in db.execute(
            sa.select(
                MarketplaceOrder.item_id,
                sa.func.count(MarketplaceOrder.id),
                sa.func.sum(MarketplaceOrder.price_cents),
            )
            .where(
                MarketplaceOrder.item_id.in_([item.id for item in owned]),
                MarketplaceOrder.status == OrderStatus.completed.value,
            )
            .group_by(MarketplaceOrder.item_id)
        ).all()
    }
    listings: list[dict[str, Any]] = [
        {
            "item_id": str(item.id),
            "title": item.title,
            "downloads": item.downloads,
            "orders": order_totals.get(item.id, (0, 0))[0],
            "gross_cents": order_totals.get(item.id, (0, 0))[1],
            "currency": item.currency,
        }
        for item in owned
    ]
    listings.sort(key=lambda row: (-row["orders"], -row["downloads"], row["title"]))
    return {
        "window_days": 30,
        "generated_at": now,
        "demand": demand,
        "listings": listings,
    }


# --- listings ---------------------------------------------------------------------------------


def _clean_tags(tags: list[str] | None) -> list[str]:
    seen: list[str] = []
    for tag in tags or []:
        clean = re.sub(r"\s+", " ", tag.strip().lower())[:40]
        if clean and clean not in seen:
            seen.append(clean)
    return seen[:MAX_TAGS]


def _summary(version: ProjectVersion) -> dict[str, Any]:
    provenance = version.provenance or {}
    bodies = provenance.get("bodies") or []
    last = bodies[-1] if bodies and isinstance(bodies[-1], dict) else {}
    bbox = last.get("bbox_mm") or {}
    return {
        "size_mm": bbox.get("size") if isinstance(bbox, dict) else None,
        "volume_mm3": last.get("volume_mm3"),
        "parametric": bool(version.provenance and (version.provenance.get("plan_goal") or bodies)),
        "operation": provenance.get("operation"),
    }


def configurable_parameters(db: Session, version_id: uuid.UUID) -> list[dict[str, Any]]:
    """Safe numeric knobs already present in the exact immutable feature tree (F-045)."""
    rows = db.scalars(
        sa.select(Operation)
        .where(Operation.project_version_id == version_id, Operation.enabled.is_(True))
        .order_by(Operation.sequence_no)
    ).all()
    effective: dict[tuple[str, str], float] = {}
    offered: list[dict[str, Any]] = []
    for row in rows:
        operation_id = str(row.params.get("id", f"op_{row.sequence_no}"))
        if row.operation_type == "set_parameter":
            target = row.params.get("operation")
            parameter = row.params.get("parameter")
            value = row.params.get("value")
            if (
                isinstance(target, str)
                and isinstance(parameter, str)
                and isinstance(value, int | float)
            ):
                effective[(target, parameter)] = float(value)
            continue
        for parameter in CONFIGURABLE_FIELDS.get(row.operation_type, ()):
            value = row.params.get(parameter)
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            offered.append(
                {
                    "key": f"{operation_id}.{parameter}",
                    "operation": operation_id,
                    "parameter": parameter,
                    "value": float(value),
                    "min": 0.0 if parameter == "top_diameter_mm" else 0.01,
                    "max": 360.0 if parameter == "angle_deg" else 10_000.0,
                    "unit": "deg" if parameter == "angle_deg" else "mm",
                }
            )
    for item in offered:
        item["value"] = effective.get((item["operation"], item["parameter"]), item["value"])
    return offered[:16]


def configuration_operations(
    db: Session,
    *,
    item: MarketplaceItem,
    values: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate buyer-selected knobs against the listing's offered exact parameters."""
    if not values:
        return []
    offered = {
        (parameter["operation"], parameter["parameter"]): parameter
        for parameter in configurable_parameters(db, item.version_id)
    }
    seen: set[tuple[str, str]] = set()
    operations: list[dict[str, Any]] = []
    for index, selected in enumerate(values, start=1):
        key = (str(selected.get("operation", "")), str(selected.get("parameter", "")))
        if key in seen or key not in offered:
            raise ValidationFailedError(
                "configuration contains an unavailable or duplicate parameter",
                {"operation": key[0], "parameter": key[1]},
            )
        seen.add(key)
        value = selected.get("value")
        parameter = offered[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not parameter["min"] <= float(value) <= parameter["max"]
        ):
            raise ValidationFailedError(
                "configuration value is outside the offered range",
                {"key": parameter["key"], "min": parameter["min"], "max": parameter["max"]},
            )
        operations.append(
            {
                "schema_version": 1,
                "id": f"marketplace_parameter_{index}",
                "type": "set_parameter",
                "operation": key[0],
                "parameter": key[1],
                "value": float(value),
            }
        )
    source = db.get(ProjectVersion, item.version_id)
    assert source is not None
    from app.services import edits

    edits.build_plan(db, version=source, operations=operations, label="Marketplace configuration")
    return operations


def publish(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None,
    title: str,
    description: str | None,
    category: str,
    tags: list[str] | None,
    price_cents: int,
    currency: str,
    license_id: str | None,
    domain: str = ListingDomain.other.value,
    subcategory: str | None = None,
) -> MarketplaceItem:
    return publish_bundle(
        db,
        user_id=user_id,
        project_id=project_id,
        version_id=version_id,
        title=title,
        description=description,
        category=category,
        domain=domain,
        subcategory=subcategory,
        tags=tags,
        price_cents=price_cents,
        currency=currency,
        license_id=license_id,
        component_version_ids=[],
    )


def publish_bundle(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None,
    title: str,
    description: str | None,
    category: str,
    domain: str,
    subcategory: str | None,
    tags: list[str] | None,
    price_cents: int,
    currency: str,
    license_id: str | None,
    component_version_ids: list[uuid.UUID],
) -> MarketplaceItem:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    chosen_version = version_id or project.head_version_id
    if chosen_version is None:
        raise ValidationFailedError("there is no model to publish yet")
    version = db.get(ProjectVersion, chosen_version)
    if version is None or version.project_id != project.id:
        raise NotFoundError("version", chosen_version)
    if version.state is not VersionState.finalized:
        raise ConflictError("only a kept (finalized) version can be listed")
    if not version.assets:
        raise ValidationFailedError("this version has no files to offer")
    if category not in ListingCategory.__members__:
        raise ValidationFailedError(
            "unknown category", {"known": list(ListingCategory.__members__)}
        )
    domain, clean_subcategory = normalize_taxonomy_pair(domain, subcategory)
    licence_id = license_id or project.license_id
    if not licence_id:
        raise ValidationFailedError(
            "choose a licence before listing: buyers must know what they may do",
            {"known": sorted(licensing.LICENCES)},
        )
    if licence_id not in licensing.LICENCES:
        raise ValidationFailedError(
            f"unknown licence {licence_id!r}", {"known": sorted(licensing.LICENCES)}
        )
    if price_cents < 0:
        raise ValidationFailedError("a price cannot be negative")
    licensing.assert_may_list_for_price(db, project, licence_id, price_cents)
    if version.id in component_version_ids or len(set(component_version_ids)) != len(
        component_version_ids
    ):
        raise ValidationFailedError("duplicate component")
    components: list[ProjectVersion] = []
    for component_id in component_version_ids:
        component = db.get(ProjectVersion, component_id)
        if component is None or component.project_id != project.id:
            raise NotFoundError("version", component_id)
        if component.state is not VersionState.finalized:
            raise ConflictError("only a kept (finalized) version can be listed")
        if not component.assets:
            raise ValidationFailedError("this version has no files to offer")
        components.append(component)
    existing = db.scalar(sa.select(MarketplaceItem).where(MarketplaceItem.version_id == version.id))
    if existing is not None:
        raise ConflictError("this version is already listed", {"listing_id": str(existing.id)})
    ensure_profile(db, user_id)
    if project.license_id is None:
        project.license_id = licence_id  # the project now says what it is offered under

    item = MarketplaceItem(
        workspace_id=project.workspace_id,
        project_id=project.id,
        version_id=version.id,
        creator_user_id=user_id,
        title=title.strip()[:200],
        description=(description or "").strip()[:5000] or None,
        category=category,
        domain=domain,
        subcategory=clean_subcategory,
        tags=_clean_tags(tags),
        price_cents=price_cents,
        currency=currency.upper()[:3],
        license_id=licence_id,
        status=ListingStatus.published.value,
        published_at=datetime.now(UTC),
        summary=_summary(version),
    )
    db.add(item)
    db.flush()
    for index, component in enumerate(components, start=1):
        db.add(
            MarketplaceItemComponent(
                item_id=item.id,
                version_id=component.id,
                label=(component.label or f"Component {index}")[:200],
                sort_order=index,
                summary=_summary(component),
            )
        )
    db.flush()
    return item


def components_for(
    db: Session, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[MarketplaceItemComponent]]:
    grouped: dict[uuid.UUID, list[MarketplaceItemComponent]] = {item_id: [] for item_id in item_ids}
    if not item_ids:
        return grouped
    rows = db.scalars(
        sa.select(MarketplaceItemComponent)
        .where(MarketplaceItemComponent.item_id.in_(item_ids))
        .order_by(MarketplaceItemComponent.item_id, MarketplaceItemComponent.sort_order)
    ).all()
    for row in rows:
        grouped.setdefault(row.item_id, []).append(row)
    return grouped


def facade_compatibility(
    db: Session,
    *,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    project_id: uuid.UUID,
) -> FacadeCompatibility:
    """Compare public bundle envelopes with one authorized, job-proven exact facade.

    This deliberately proves only persisted bounding-box compatibility. It never reads the
    creator's private mesh and never promotes this result to the post-acquisition mesh fit test.
    """
    item = get_listing(db, user_id=user_id, item_id=item_id)
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    version = db.get(ProjectVersion, project.head_version_id) if project.head_version_id else None
    if version is None:
        return FacadeCompatibility(project, None, "unsupported", "project_has_no_model", (), 0)

    producing_job = next(
        (
            job
            for job in db.scalars(
                sa.select(Job)
                .where(
                    Job.project_id == project.id,
                    Job.type == "edit_facade",
                    Job.status == JobStatus.succeeded,
                )
                .order_by(Job.created_at.desc(), Job.id.desc())
            ).all()
            if isinstance(job.result, dict)
            and job.result.get("version_id") == str(version.id)
        ),
        None,
    )
    if producing_job is None:
        return FacadeCompatibility(
            project, version, "unsupported", "head_is_not_exact_facade", (), 0
        )
    try:
        facade = FacadeRequest(**dict(producing_job.input.get("request") or {}))
    except (TypeError, ValueError, ValidationError):
        return FacadeCompatibility(
            project, version, "unsupported", "invalid_saved_facade", (), 0
        )
    if not facade.openings:
        return FacadeCompatibility(project, version, "unsupported", "facade_has_no_openings", (), 0)

    members: list[tuple[uuid.UUID, str, dict[str, Any]]] = [
        (item.version_id, item.title, dict(item.summary or {}))
    ]
    members.extend(
        (row.version_id, row.label, dict(row.summary or {}))
        for row in components_for(db, [item.id]).get(item.id, [])
    )

    def measured_envelope(summary: dict[str, Any]) -> tuple[float, float, float] | None:
        raw = summary.get("size_mm")
        if (
            not isinstance(raw, list)
            or len(raw) != 3
            or any(not isinstance(value, int | float) or value <= 0 for value in raw)
        ):
            return None
        depth, first, second = sorted(float(value) for value in raw)
        return depth, first, second

    openings: list[dict[str, Any]] = []
    matched_openings = 0
    for index, opening in enumerate(facade.openings):
        wanted = sorted((float(opening.width_mm), float(opening.height_mm)))
        matches: list[dict[str, Any]] = []
        for version_id, label, summary in members:
            envelope = measured_envelope(summary)
            if envelope is None:
                continue
            depth, first, second = envelope
            if depth > float(facade.wall_thickness_mm) + FACADE_SIZE_TOLERANCE_MM:
                continue
            if (
                abs(first - wanted[0]) <= FACADE_SIZE_TOLERANCE_MM
                and abs(second - wanted[1]) <= FACADE_SIZE_TOLERANCE_MM
            ):
                matches.append(
                    {
                        "version_id": version_id,
                        "label": label,
                        "size_mm": list(summary["size_mm"]),
                    }
                )
        if matches:
            matched_openings += 1
        openings.append(
            {
                "opening_id": opening_key(opening, index),
                "kind": opening.kind,
                "side": opening.side,
                "floor": opening.floor,
                "center_mm": float(opening.center_mm),
                "width_mm": float(opening.width_mm),
                "height_mm": float(opening.height_mm),
                "sill_mm": float(opening.sill_mm),
                "matches": matches,
            }
        )
    status = (
        "complete"
        if matched_openings == len(openings)
        else "partial"
        if matched_openings
        else "incompatible"
    )
    return FacadeCompatibility(
        project, version, status, None, tuple(openings), matched_openings
    )


def get_listing(db: Session, *, user_id: uuid.UUID, item_id: uuid.UUID) -> MarketplaceItem:
    """A published listing is public; anything else only its creator sees."""
    item = db.get(MarketplaceItem, item_id)
    if item is None:
        raise NotFoundError("listing", item_id)
    if item.status != ListingStatus.published.value and item.creator_user_id != user_id:
        raise NotFoundError("listing", item_id)
    return item


def update_listing(
    db: Session,
    *,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    title: str | None = None,
    description: str | None = None,
    category: str | None = None,
    domain: str | None = None,
    subcategory: str | None = None,
    subcategory_set: bool = False,
    tags: list[str] | None = None,
    price_cents: int | None = None,
    status: str | None = None,
) -> MarketplaceItem:
    item = db.get(MarketplaceItem, item_id)
    if item is None or item.creator_user_id != user_id:
        raise NotFoundError("listing", item_id)
    if title is not None:
        if not title.strip():
            raise ValidationFailedError("title must not be empty")
        item.title = title.strip()[:200]
    if description is not None:
        item.description = description.strip()[:5000] or None
    if category is not None:
        if category not in ListingCategory.__members__:
            raise ValidationFailedError("unknown category")
        item.category = category
    if domain is not None or subcategory_set:
        next_domain = domain if domain is not None else item.domain
        next_subcategory = subcategory if subcategory_set else item.subcategory
        item.domain, item.subcategory = normalize_taxonomy_pair(next_domain, next_subcategory)
    if tags is not None:
        item.tags = _clean_tags(tags)
    if price_cents is not None:
        if price_cents < 0:
            raise ValidationFailedError("a price cannot be negative")
        project = db.get(Project, item.project_id)
        assert project is not None
        licensing.assert_may_list_for_price(db, project, item.license_id, price_cents)
        item.price_cents = price_cents
    if status is not None:
        if status not in (ListingStatus.published.value, ListingStatus.withdrawn.value):
            raise ValidationFailedError("a creator can publish or withdraw a listing")
        if item.status == ListingStatus.blocked.value:
            raise ConflictError("this listing was blocked by moderation")
        if status == ListingStatus.published.value and item.status != status:
            item.published_at = datetime.now(UTC)
        item.status = status
    db.flush()
    return item


def my_listings(db: Session, user_id: uuid.UUID) -> list[MarketplaceItem]:
    return list(
        db.scalars(
            sa.select(MarketplaceItem)
            .where(MarketplaceItem.creator_user_id == user_id)
            .order_by(MarketplaceItem.created_at.desc(), MarketplaceItem.id)
        )
    )


def listings_of_project(db: Session, project_id: uuid.UUID) -> list[MarketplaceItem]:
    return list(
        db.scalars(
            sa.select(MarketplaceItem)
            .where(MarketplaceItem.project_id == project_id)
            .order_by(MarketplaceItem.created_at.desc())
        )
    )


def search(
    db: Session,
    *,
    q: str | None = None,
    category: str | None = None,
    domain: str | None = None,
    subcategory: str | None = None,
    creator_handle: str | None = None,
    free_only: bool = False,
    min_price_cents: int | None = None,
    max_price_cents: int | None = None,
    bundle_only: bool = False,
    format_id: str | None = None,
    editable_only: bool = False,
    has_2d_plan: bool = False,
    print_ready: bool = False,
    max_width_mm: float | None = None,
    max_depth_mm: float | None = None,
    max_height_mm: float | None = None,
    rotate_to_fit: bool = False,
    sort: str = "newest",
    limit: int = 30,
    offset: int = 0,
) -> list[MarketplaceItem]:
    """Published listings filtered by words and by an optional physical envelope.

    A dimensional search never guesses: listings without measured ``size_mm`` evidence are
    excluded. ``rotate_to_fit`` permits any axis permutation, but only when the caller supplied
    a complete three-dimensional envelope.
    """
    query = sa.select(MarketplaceItem).where(
        MarketplaceItem.status == ListingStatus.published.value
    )
    search_words: list[str] = []
    clean_query = ""
    if q and q.strip():
        clean_query = " ".join(q.strip().split())
        search_words = clean_query.split()[:6]
        for word in search_words:
            like = f"%{word}%"
            query = query.where(
                sa.or_(
                    MarketplaceItem.title.ilike(like),
                    MarketplaceItem.description.ilike(like),
                    sa.cast(MarketplaceItem.tags, sa.Text).ilike(like),
                )
            )
    if category:
        query = query.where(MarketplaceItem.category == category)
    if domain:
        query = query.where(MarketplaceItem.domain == domain)
    if subcategory:
        query = query.where(MarketplaceItem.subcategory == subcategory)
    if creator_handle:
        creator = profile_by_handle(db, creator_handle)
        query = query.where(MarketplaceItem.creator_user_id == creator.user_id)
    if free_only:
        query = query.where(MarketplaceItem.price_cents == 0)
    if min_price_cents is not None and max_price_cents is not None:
        if min_price_cents > max_price_cents:
            raise ValidationFailedError(
                "minimum price cannot exceed maximum price",
                {"min_price_cents": min_price_cents, "max_price_cents": max_price_cents},
            )
    if min_price_cents is not None:
        query = query.where(MarketplaceItem.price_cents >= min_price_cents)
    if max_price_cents is not None:
        query = query.where(MarketplaceItem.price_cents <= max_price_cents)
    if bundle_only:
        query = query.where(
            sa.exists().where(MarketplaceItemComponent.item_id == MarketplaceItem.id)
        )
    if format_id:
        clean_format = format_id.strip().lower()
        query = query.where(
            sa.exists(
                sa.select(VersionAsset.version_id)
                .join(Asset, Asset.id == VersionAsset.asset_id)
                .where(
                    VersionAsset.version_id == MarketplaceItem.version_id,
                    VersionAsset.role.in_((AssetRole.source, AssetRole.model, AssetRole.export)),
                    sa.func.lower(Asset.format) == clean_format,
                )
            )
        )
    if editable_only:
        query = query.where(
            sa.exists(
                sa.select(Operation.id).where(
                    Operation.project_version_id == MarketplaceItem.version_id,
                    Operation.enabled.is_(True),
                )
            )
        )
    if print_ready:
        latest_print_status = (
            sa.select(PrintAnalysisRecord.status)
            .where(
                PrintAnalysisRecord.project_version_id == MarketplaceItem.version_id,
                PrintAnalysisRecord.kind == AnalysisKind.analysis,
            )
            .order_by(PrintAnalysisRecord.created_at.desc(), PrintAnalysisRecord.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        query = query.where(latest_print_status == "green")
    if sort == "relevant" and search_words:
        # Explainable, data-only ranking: an exact or prefix title wins, then each matched
        # word contributes more in the title than in tags, and more in tags than in the
        # description. The existing filters above still require every word to match.
        relevance: Any = sa.case(
            (sa.func.lower(MarketplaceItem.title) == clean_query.lower(), 100),
            (MarketplaceItem.title.ilike(f"{clean_query}%"), 50),
            else_=0,
        )
        for word in search_words:
            like = f"%{word}%"
            relevance += sa.case((MarketplaceItem.title.ilike(like), 6), else_=0)
            relevance += sa.case((sa.cast(MarketplaceItem.tags, sa.Text).ilike(like), 3), else_=0)
            relevance += sa.case((MarketplaceItem.description.ilike(like), 1), else_=0)
        query = query.order_by(
            relevance.desc(), MarketplaceItem.published_at.desc(), MarketplaceItem.id
        )
    elif sort == "popular":
        query = query.order_by(
            MarketplaceItem.downloads.desc(), MarketplaceItem.published_at.desc()
        )
    elif sort == "cheapest":
        query = query.order_by(MarketplaceItem.price_cents, MarketplaceItem.published_at.desc())
    else:
        query = query.order_by(MarketplaceItem.published_at.desc(), MarketplaceItem.id)
    dimensional = any(value is not None for value in (max_width_mm, max_depth_mm, max_height_mm))
    if not dimensional and not has_2d_plan:
        return list(db.scalars(query.limit(min(limit, SEARCH_LIMIT)).offset(offset)))

    envelope = (max_width_mm, max_depth_mm, max_height_mm)
    if rotate_to_fit and any(value is None for value in envelope):
        raise ValidationFailedError(
            "rotate_to_fit requires width, depth and height",
            {"required": ["max_width_mm", "max_depth_mm", "max_height_mm"]},
        )

    def fits(item: MarketplaceItem) -> bool:
        raw = (item.summary or {}).get("size_mm")
        if (
            not isinstance(raw, list)
            or len(raw) != 3
            or any(not isinstance(value, (int, float)) or value <= 0 for value in raw)
        ):
            return False
        size = tuple(float(value) for value in raw)
        if rotate_to_fit:
            spaces = sorted(float(value) for value in envelope if value is not None)
            return all(part <= space for part, space in zip(sorted(size), spaces, strict=True))
        return all(
            space is None or part <= space for part, space in zip(size, envelope, strict=True)
        )

    # Apply pagination after evidence predicates so a page never contains false matches.
    matching = list(db.scalars(query).all())
    if has_2d_plan:
        candidate_version_ids = [item.version_id for item in matching]
        proven_plan_versions = {
            version.id
            for version in db.scalars(
                sa.select(ProjectVersion).where(ProjectVersion.id.in_(candidate_version_ids))
            ).all()
            if has_2d_plan_evidence(version.provenance)
        }
        matching = [item for item in matching if item.version_id in proven_plan_versions]
    if dimensional:
        matching = [item for item in matching if fits(item)]
    return matching[offset : offset + min(limit, SEARCH_LIMIT)]


def marketplace_facets(db: Session) -> list[dict[str, Any]]:
    """The complete editorial taxonomy with published counts, including zeroes."""
    domains: dict[str, dict[str, Any]] = {}
    for domain_order, (domain_id, taxonomy) in enumerate(MARKETPLACE_TAXONOMY.items()):
        domains[domain_id] = {
            "id": domain_id,
            "label_en": taxonomy["label_en"],
            "label_ru": taxonomy["label_ru"],
            "order": domain_order,
            "count": 0,
            "subcategories": [
                {
                    "id": subcategory_id,
                    "label_en": label_en,
                    "label_ru": label_ru,
                    "order": subcategory_order,
                    "count": 0,
                }
                for subcategory_order, (subcategory_id, label_en, label_ru) in enumerate(
                    taxonomy["subcategories"]
                )
            ],
        }
    rows = db.execute(
        sa.select(
            MarketplaceItem.domain,
            MarketplaceItem.subcategory,
            sa.func.count(MarketplaceItem.id),
        )
        .where(MarketplaceItem.status == ListingStatus.published.value)
        .group_by(MarketplaceItem.domain, MarketplaceItem.subcategory)
        .order_by(MarketplaceItem.domain, MarketplaceItem.subcategory)
    ).all()
    for domain, subcategory, count in rows:
        facet = domains.get(domain)
        if facet is None:
            continue
        amount = int(count)
        facet["count"] += amount
        if subcategory:
            child = next((row for row in facet["subcategories"] if row["id"] == subcategory), None)
            if child is not None:
                child["count"] = amount
    return list(domains.values())


# --- favorites ---------------------------------------------------------------------------------


def favorite_add(db: Session, *, user_id: uuid.UUID, item_id: uuid.UUID) -> MarketplaceItem:
    item = get_listing(db, user_id=user_id, item_id=item_id)
    if item.status != ListingStatus.published.value:
        raise ConflictError("this listing is not on offer")
    if db.get(MarketplaceFavorite, (user_id, item_id)) is None:
        db.add(MarketplaceFavorite(user_id=user_id, item_id=item_id))
        db.flush()
    return item


def favorite_remove(db: Session, *, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
    row = db.get(MarketplaceFavorite, (user_id, item_id))
    if row is not None:
        db.delete(row)
        db.flush()


def favorites(db: Session, *, user_id: uuid.UUID) -> list[MarketplaceItem]:
    return list(
        db.scalars(
            sa.select(MarketplaceItem)
            .join(MarketplaceFavorite, MarketplaceFavorite.item_id == MarketplaceItem.id)
            .where(
                MarketplaceFavorite.user_id == user_id,
                MarketplaceItem.status == ListingStatus.published.value,
            )
            .order_by(MarketplaceFavorite.saved_at.desc(), MarketplaceItem.id)
        )
    )


# --- cart --------------------------------------------------------------------------------------


def cart_add(
    db: Session, *, user_id: uuid.UUID, workspace_id: uuid.UUID, item_id: uuid.UUID
) -> MarketplaceItem:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    item = get_listing(db, user_id=user_id, item_id=item_id)
    if item.status != ListingStatus.published.value:
        raise ConflictError("this listing is not on offer")
    if item.workspace_id == workspace_id:
        raise ValidationFailedError("this listing already lives in that workspace")
    key = (user_id, workspace_id, item_id)
    if db.get(MarketplaceCartItem, key) is None:
        db.add(
            MarketplaceCartItem(
                user_id=user_id,
                workspace_id=workspace_id,
                item_id=item_id,
            )
        )
        db.flush()
    return item


def cart_remove(
    db: Session, *, user_id: uuid.UUID, workspace_id: uuid.UUID, item_id: uuid.UUID
) -> None:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    row = db.get(MarketplaceCartItem, (user_id, workspace_id, item_id))
    if row is not None:
        db.delete(row)
        db.flush()


def cart_list(db: Session, *, user_id: uuid.UUID, workspace_id: uuid.UUID) -> list[MarketplaceItem]:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    return list(
        db.scalars(
            sa.select(MarketplaceItem)
            .join(MarketplaceCartItem, MarketplaceCartItem.item_id == MarketplaceItem.id)
            .where(
                MarketplaceCartItem.user_id == user_id,
                MarketplaceCartItem.workspace_id == workspace_id,
                MarketplaceItem.status == ListingStatus.published.value,
            )
            .order_by(MarketplaceCartItem.added_at, MarketplaceItem.id)
        )
    )


def cart_total_cents(db: Session, *, user_id: uuid.UUID, workspace_id: uuid.UUID) -> int:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    return int(
        db.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(MarketplaceItem.price_cents), 0))
            .join(MarketplaceCartItem, MarketplaceCartItem.item_id == MarketplaceItem.id)
            .where(
                MarketplaceCartItem.user_id == user_id,
                MarketplaceCartItem.workspace_id == workspace_id,
                MarketplaceItem.status == ListingStatus.published.value,
            )
        )
        or 0
    )


# --- acquiring ---------------------------------------------------------------------------------


def acquire(
    db: Session,
    storage: ObjectStorage,
    settings: Settings,
    *,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> tuple[MarketplaceOrder, Project]:
    """Take a listing into a workspace: pay if it costs, then copy the version in."""
    from app.payments import provider_for
    from app.services import assets as asset_services
    from app.services.scenes import IDENTITY, SCENE_SCHEMA_VERSION

    item = get_listing(db, user_id=user_id, item_id=item_id)
    if item.status != ListingStatus.published.value:
        raise ConflictError("this listing is not on offer")
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.editor)
    if item.workspace_id == workspace_id:
        raise ValidationFailedError("this listing already lives in that workspace")
    already = db.scalar(
        sa.select(MarketplaceOrder).where(
            MarketplaceOrder.item_id == item.id, MarketplaceOrder.workspace_id == workspace_id
        )
    )
    if already is not None and already.project_id is not None:
        project = db.get(Project, already.project_id)
        if project is not None and project.deleted_at is None:
            return already, project

    charge = None
    if item.price_cents > 0:
        charge = provider_for(settings).charge(
            amount_cents=item.price_cents, currency=item.currency, description=item.title
        )

    source = db.get(ProjectVersion, item.version_id)
    assert source is not None
    components = db.scalars(
        sa.select(MarketplaceItemComponent)
        .where(MarketplaceItemComponent.item_id == item.id)
        .order_by(MarketplaceItemComponent.sort_order)
    ).all()
    creator = ensure_profile(db, item.creator_user_id)
    licence = licensing.LICENCES[item.license_id]
    project = projects.create_project(
        db,
        user_id=user_id,
        workspace_id=workspace_id,
        name=item.title,
        description=item.description,
    )
    project.license_id = item.license_id
    project.attribution = f"{item.title} by @{creator.handle} ({licence.name})"[:300]
    project.remixed_from_project_id = item.project_id
    db.flush()

    copied_assets = {
        link.role: copy_asset_to_workspace(
            db, storage, link.asset, workspace_id=workspace_id, created_by=user_id
        ).id
        for link in source.assets
    }
    provenance = {
        **(source.provenance or {}),
        "operation": "acquire",
        "listing_id": str(item.id),
        "source_version_id": str(source.id),
        "creator_handle": creator.handle,
        "license_id": item.license_id,
    }
    if not components:
        version = projects.create_version_internal(
            db,
            project_id=project.id,
            parent_version_id=None,
            label=f"{item.title} (marketplace)",
            provenance=provenance,
            assets=copied_assets,
            finalize=True,
            created_by=user_id,
        )
    else:
        anchor_model = copied_assets.get(AssetRole.model)
        if anchor_model is None:
            source_model = asset_services.model_asset_of(db, source)
            if source_model is None:
                raise ValidationFailedError("this version has no model file to offer")
            anchor_model = copy_asset_to_workspace(
                db, storage, source_model, workspace_id=workspace_id, created_by=user_id
            ).id
        members: list[tuple[str, uuid.UUID]] = [(item.title, anchor_model)]
        for component in components:
            component_version = db.get(ProjectVersion, component.version_id)
            if component_version is None:
                raise ValidationFailedError(
                    "a bundle component is unavailable", {"component_id": str(component.id)}
                )
            component_model = asset_services.model_asset_of(db, component_version)
            if component_model is None:
                raise ValidationFailedError(
                    "a bundle component has no model file",
                    {"component_id": str(component.id)},
                )
            copied = copy_asset_to_workspace(
                db, storage, component_model, workspace_id=workspace_id, created_by=user_id
            )
            members.append((component.label, copied.id))
        nodes = [
            {
                "id": "bundle_anchor" if index == 0 else f"bundle_component_{index}",
                "name": label,
                "kind": "object",
                "parent_id": None,
                "visible": True,
                "transform": [row[:] for row in IDENTITY],
                "asset_id": str(asset_id),
                "instance_of": None,
            }
            for index, (label, asset_id) in enumerate(members)
        ]
        provenance["scene"] = {"schema_version": SCENE_SCHEMA_VERSION, "nodes": nodes}
        non_model_assets: dict[AssetRole, uuid.UUID] = {
            role: asset_id
            for role, asset_id in copied_assets.items()
            if role is not AssetRole.model
        }
        version = projects.create_version_internal(
            db,
            project_id=project.id,
            parent_version_id=None,
            label=f"{item.title} (marketplace)",
            provenance=provenance,
            assets=non_model_assets,
            finalize=False,
            created_by=user_id,
        )
        for asset_id in dict.fromkeys(asset_id for _, asset_id in members):
            projects.attach_asset(db, version, asset_id, AssetRole.model, workspace_id=workspace_id)
        projects.finalize_version(db, version)
    rows = db.scalars(
        sa.select(Operation)
        .where(Operation.project_version_id == source.id)
        .order_by(Operation.sequence_no)
    ).all()
    for row in rows:
        db.add(
            Operation(
                project_version_id=version.id,
                sequence_no=row.sequence_no,
                operation_type=row.operation_type,
                schema_version=row.schema_version,
                params=row.params,
                entity_refs=row.entity_refs,
                enabled=row.enabled,
                ai_request_id=None,
            )
        )
    order = already or MarketplaceOrder(
        item_id=item.id,
        buyer_user_id=user_id,
        workspace_id=workspace_id,
        price_cents=item.price_cents,
        currency=item.currency,
    )
    order.project_id = project.id
    order.status = OrderStatus.completed.value
    if charge is not None:
        order.payment_provider = charge.provider
        order.payment_reference = charge.reference
    db.add(order)
    item.downloads += 1
    db.flush()
    return order, project


def my_orders(db: Session, user_id: uuid.UUID) -> list[MarketplaceOrder]:
    return list(
        db.scalars(
            sa.select(MarketplaceOrder)
            .where(MarketplaceOrder.buyer_user_id == user_id)
            .order_by(MarketplaceOrder.created_at.desc(), MarketplaceOrder.id)
        )
    )


def order_files(
    db: Session, *, user_id: uuid.UUID, order_id: uuid.UUID
) -> list[DeliveredMarketplaceFile]:
    """Return the concrete buyer-owned files delivered by one completed order."""
    order = db.scalar(
        sa.select(MarketplaceOrder).where(
            MarketplaceOrder.id == order_id,
            MarketplaceOrder.buyer_user_id == user_id,
        )
    )
    if order is None or order.status != OrderStatus.completed.value or order.project_id is None:
        raise NotFoundError("marketplace order", order_id)
    require_workspace_role(db, user_id, order.workspace_id, WorkspaceRole.viewer)

    delivered_version = next(
        (
            version
            for version in db.scalars(
                sa.select(ProjectVersion)
                .where(ProjectVersion.project_id == order.project_id)
                .order_by(ProjectVersion.sequence_no, ProjectVersion.id)
            ).all()
            if (version.provenance or {}).get("operation") == "acquire"
            and (version.provenance or {}).get("listing_id") == str(order.item_id)
        ),
        None,
    )
    if delivered_version is None:
        raise NotFoundError("marketplace delivery", order_id)

    item = db.get(MarketplaceItem, order.item_id)
    default_label = item.title if item is not None else "Marketplace file"
    labels_by_asset_id: dict[str, list[str]] = {}
    scene = (delivered_version.provenance or {}).get("scene")
    raw_nodes = scene.get("nodes") if isinstance(scene, dict) else None
    if isinstance(raw_nodes, list):
        for node in raw_nodes:
            if not isinstance(node, dict):
                continue
            asset_id = node.get("asset_id")
            name = node.get("name")
            if isinstance(asset_id, str) and isinstance(name, str) and name.strip():
                clean_name = name.strip()[:200]
                labels = labels_by_asset_id.setdefault(asset_id, [])
                if clean_name not in labels:
                    labels.append(clean_name)

    deliverable_roles = (AssetRole.source, AssetRole.model, AssetRole.export)
    rows = (
        db.execute(
            sa.select(VersionAsset, Asset)
            .join(Asset, Asset.id == VersionAsset.asset_id)
            .where(
                VersionAsset.version_id == delivered_version.id,
                VersionAsset.role.in_(deliverable_roles),
                Asset.workspace_id == order.workspace_id,
                Asset.format.is_not(None),
            )
            .order_by(VersionAsset.role, Asset.format, Asset.id)
        )
        .tuples()
        .all()
    )
    return [
        DeliveredMarketplaceFile(
            asset=asset,
            role=link.role,
            labels=tuple(labels_by_asset_id.get(str(asset.id), [default_label])),
        )
        for link, asset in rows
    ]
