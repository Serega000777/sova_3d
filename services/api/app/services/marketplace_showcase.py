"""Idempotent, non-production marketplace showcase built through canonical services.

The marketplace UI must remain empty when production data is empty.  Local/demo operators can
run this explicit seed instead: it creates ordinary users, workspaces, projects, immutable
versions, content-addressed assets and listings, so every card still exercises the real product
path instead of a UI-only fixture.
"""

from __future__ import annotations

import hashlib
import html
import uuid
from dataclasses import dataclass
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.core import (
    Project,
    Units,
    User,
    Workspace,
    WorkspaceKind,
    WorkspaceMember,
    WorkspaceRole,
)
from app.models.marketplace import MarketplaceItem
from app.models.versioning import (
    Asset,
    AssetKind,
    AssetRole,
    ProjectVersion,
    ThumbnailAngle,
    VersionAsset,
)
from app.services import marketplace, projects
from app.storage import ObjectStorage

SHOWCASE_VERSION = "marketplace-showcase:v1"


@dataclass(frozen=True, slots=True)
class ShowcasePart:
    label: str
    size_mm: tuple[float, float, float]
    colour: str


@dataclass(frozen=True, slots=True)
class ShowcaseProduct:
    slug: str
    creator_slug: str
    creator_name: str
    title: str
    description: str
    category: Literal["print", "game", "arvr", "cad", "other"]
    tags: tuple[str, ...]
    price_cents: int
    licence_id: str
    size_mm: tuple[float, float, float]
    colour: str
    downloads: int
    components: tuple[ShowcasePart, ...] = ()


PRODUCTS: tuple[ShowcaseProduct, ...] = (
    ShowcaseProduct(
        slug="desk-organizer",
        creator_slug="sova-lab",
        creator_name="Sova Lab",
        title="Модульный органайзер",
        description="Печатный настольный органайзер с секциями для кабелей и мелких деталей.",
        category="print",
        tags=("органайзер", "стол", "печать", "модульный"),
        price_cents=0,
        licence_id="CC-BY-4.0",
        size_mm=(160.0, 92.0, 48.0),
        colour="#ff7a1a",
        downloads=128,
    ),
    ShowcaseProduct(
        slug="parametric-planter",
        creator_slug="forma-studio",
        creator_name="Forma Studio",
        title="Параметрическое кашпо",
        description="Редактируемое CAD-кашпо с дренажным основанием и спокойной гранёной формой.",
        category="cad",
        tags=("кашпо", "интерьер", "cad", "параметрический"),
        price_cents=1299,
        licence_id="CC-BY-4.0",
        size_mm=(180.0, 180.0, 210.0),
        colour="#c46cff",
        downloads=46,
    ),
    ShowcaseProduct(
        slug="low-poly-rover",
        creator_slug="north-pixel",
        creator_name="North Pixel",
        title="Low-poly марсоход",
        description="Оптимизированная игровая модель марсохода для прототипов и AR-сцен.",
        category="game",
        tags=("марсоход", "low-poly", "игра", "ar"),
        price_cents=850,
        licence_id="CC-BY-4.0",
        size_mm=(2400.0, 1500.0, 1200.0),
        colour="#42b8a5",
        downloads=73,
    ),
    ShowcaseProduct(
        slug="facade-kit",
        creator_slug="forma-studio",
        creator_name="Forma Studio",
        title="Набор фасадных модулей",
        description="Комплект согласованных оконных, дверных и декоративных фасадных элементов.",
        category="cad",
        tags=("фасад", "архитектура", "набор", "дом"),
        price_cents=2400,
        licence_id="CC-BY-SA-4.0",
        size_mm=(1200.0, 180.0, 1500.0),
        colour="#e8b04b",
        downloads=31,
        components=(
            ShowcasePart("Дверной модуль", (1000.0, 180.0, 2200.0), "#d77a32"),
            ShowcasePart("Карнизный модуль", (1800.0, 240.0, 260.0), "#f0cf7a"),
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class ShowcaseSummary:
    creators: int
    listings: int
    created_listings: int


def _box_stl(size: tuple[float, float, float], name: str) -> bytes:
    x, y, z = size
    points = (
        (0.0, 0.0, 0.0),
        (x, 0.0, 0.0),
        (x, y, 0.0),
        (0.0, y, 0.0),
        (0.0, 0.0, z),
        (x, 0.0, z),
        (x, y, z),
        (0.0, y, z),
    )
    faces = (
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
    )
    lines = [f"solid {name}"]
    for a, b, c in faces:
        lines.extend((
            "  facet normal 0 0 0",
            "    outer loop",
            f"      vertex {points[a][0]} {points[a][1]} {points[a][2]}",
            f"      vertex {points[b][0]} {points[b][1]} {points[b][2]}",
            f"      vertex {points[c][0]} {points[c][1]} {points[c][2]}",
            "    endloop",
            "  endfacet",
        ))
    lines.append(f"endsolid {name}")
    return ("\n".join(lines) + "\n").encode()


def _thumbnail_svg(title: str, colour: str, size: tuple[float, float, float]) -> bytes:
    safe_title = html.escape(title)
    dimensions = " × ".join(f"{value:g}" for value in size)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="640"
 viewBox="0 0 960 640">
<rect width="960" height="640" fill="#111113"/>
<circle cx="760" cy="120" r="210" fill="{colour}" opacity=".16"/>
<path d="M250 238 470 130l240 116-224 122z" fill="{colour}"/>
<path d="M250 238v170l236 126V368z" fill="#29292d"/>
<path d="m486 368 224-122v168L486 534z" fill="#1d1d20"/>
<path d="M250 238 470 130l240 116-224 122z" fill="none" stroke="#fff"
 stroke-opacity=".35" stroke-width="4"/>
<text x="64" y="78" fill="#ff7a1a" font-family="sans-serif" font-size="28"
 font-weight="700">SOVA 3D</text>
<text x="64" y="570" fill="#fff" font-family="sans-serif" font-size="34"
 font-weight="700">{safe_title}</text>
<text x="64" y="608" fill="#a8a8ae" font-family="monospace" font-size="20">{dimensions} mm</text>
</svg>""".encode()


def _asset(
    db: Session,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    data: bytes,
    extension: str,
    mime: str,
    format_id: str,
    units: Units | None,
    metadata: dict[str, object],
) -> Asset:
    digest = hashlib.sha256(data).hexdigest()
    existing = db.scalar(
        sa.select(Asset).where(Asset.workspace_id == workspace_id, Asset.sha256 == digest)
    )
    if existing is not None:
        storage.put(existing.storage_key, data, existing.mime)
        return existing
    key = storage.object_key(workspace_id, digest, extension)
    storage.put(key, data, mime)
    asset = Asset(
        workspace_id=workspace_id,
        kind=AssetKind.derived,
        sha256=digest,
        storage_key=key,
        mime=mime,
        format=format_id,
        byte_size=len(data),
        units=units,
        metadata_={**metadata, "showcase_version": SHOWCASE_VERSION},
        created_by=user_id,
    )
    db.add(asset)
    db.flush()
    return asset


def _creator(db: Session, product: ShowcaseProduct) -> tuple[User, Workspace]:
    email = f"showcase+{product.creator_slug}@sova3d.local"
    user = db.scalar(sa.select(User).where(User.email == email))
    workspace: Workspace | None = None
    if user is None:
        user = User(email=email, display_name=product.creator_name, locale="ru", plan="pro")
        workspace = Workspace(
            name=f"{product.creator_name} · Showcase",
            kind=WorkspaceKind.personal,
            owner=user,
        )
        db.add_all((user, workspace))
        db.flush()
        db.add(WorkspaceMember(workspace=workspace, user=user, role=WorkspaceRole.owner))
        db.flush()
    else:
        workspace = db.scalar(sa.select(Workspace).where(Workspace.owner_user_id == user.id))
        if workspace is None:
            workspace = Workspace(
                name=f"{product.creator_name} · Showcase",
                kind=WorkspaceKind.personal,
                owner=user,
            )
            db.add(workspace)
            db.flush()
            db.add(WorkspaceMember(workspace=workspace, user=user, role=WorkspaceRole.owner))
            db.flush()
    assert workspace is not None
    marketplace.upsert_profile(
        db,
        user_id=user.id,
        handle=product.creator_slug,
        display_name=product.creator_name,
        bio="Демонстрационный автор локального каталога Sova 3D.",
        website=None,
    )
    return user, workspace


def _version(
    db: Session,
    storage: ObjectStorage,
    *,
    user: User,
    workspace: Workspace,
    project_id: uuid.UUID,
    label: str,
    title: str,
    colour: str,
    size: tuple[float, float, float],
) -> ProjectVersion:
    version = db.scalar(
        sa.select(ProjectVersion).where(
            ProjectVersion.project_id == project_id, ProjectVersion.label == label
        )
    )
    if version is None:
        model = _asset(
            db,
            storage,
            workspace_id=workspace.id,
            user_id=user.id,
            data=_box_stl(size, label.replace(" ", "_")),
            extension="stl",
            mime="model/stl",
            format_id="stl",
            units=Units.mm,
            metadata={"showcase_role": "model", "label": label},
        )
        x, y, z = size
        version = projects.create_version(
            db,
            user_id=user.id,
            project_id=project_id,
            label=label,
            provenance={
                "operation": "marketplace_showcase",
                "showcase_version": SHOWCASE_VERSION,
                "bodies": [
                    {
                        "name": label,
                        "bbox_mm": {"size": list(size)},
                        "volume_mm3": x * y * z,
                    }
                ],
            },
            assets={AssetRole.model: model.id},
        )
    thumbnail_link = db.scalar(
        sa.select(VersionAsset).where(
            VersionAsset.version_id == version.id,
            VersionAsset.role == AssetRole.thumbnail,
            VersionAsset.thumbnail_angle == ThumbnailAngle.iso.value,
        )
    )
    if thumbnail_link is None:
        thumbnail = _asset(
            db,
            storage,
            workspace_id=workspace.id,
            user_id=user.id,
            data=_thumbnail_svg(title, colour, size),
            extension="svg",
            mime="image/svg+xml",
            format_id="svg",
            units=None,
            metadata={"showcase_role": "thumbnail", "thumbnail_angle": "iso"},
        )
        projects.attach_asset(
            db,
            version,
            thumbnail.id,
            AssetRole.thumbnail,
            workspace_id=workspace.id,
            thumbnail_angle=ThumbnailAngle.iso.value,
        )
    return version


def seed_marketplace_showcase(
    db: Session,
    storage: ObjectStorage,
    *,
    app_env: str,
) -> ShowcaseSummary:
    """Create or repair the canonical local showcase; refuse production unconditionally."""
    if app_env == "production":
        raise ValueError("marketplace showcase seed is forbidden in production")
    created = 0
    creator_ids: set[uuid.UUID] = set()
    for product in PRODUCTS:
        user, workspace = _creator(db, product)
        creator_ids.add(user.id)
        marker = f"[{SHOWCASE_VERSION}:{product.slug}]"
        project = db.scalar(
            sa.select(Project).where(
                Project.workspace_id == workspace.id,
                Project.description == marker,
            )
        )
        if project is None:
            project = projects.create_project(
                db,
                user_id=user.id,
                workspace_id=workspace.id,
                name=product.title,
                description=marker,
            )
        anchor = _version(
            db,
            storage,
            user=user,
            workspace=workspace,
            project_id=project.id,
            label="Showcase anchor",
            title=product.title,
            colour=product.colour,
            size=product.size_mm,
        )
        component_ids = [
            _version(
                db,
                storage,
                user=user,
                workspace=workspace,
                project_id=project.id,
                label=part.label,
                title=part.label,
                colour=part.colour,
                size=part.size_mm,
            ).id
            for part in product.components
        ]
        listing = db.scalar(
            sa.select(MarketplaceItem).where(MarketplaceItem.version_id == anchor.id)
        )
        if listing is None:
            listing = marketplace.publish_bundle(
                db,
                user_id=user.id,
                project_id=project.id,
                version_id=anchor.id,
                title=product.title,
                description=product.description,
                category=product.category,
                tags=list(product.tags),
                price_cents=product.price_cents,
                currency="USD",
                license_id=product.licence_id,
                component_version_ids=component_ids,
            )
            created += 1
        listing.downloads = product.downloads
    db.flush()
    return ShowcaseSummary(
        creators=len(creator_ids),
        listings=len(PRODUCTS),
        created_listings=created,
    )
