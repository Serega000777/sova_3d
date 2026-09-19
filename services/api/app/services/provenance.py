"""Model provenance graph (T-154, F-079): where every version came from, in one picture.

Versions and their parents; the commands that made them; the scans they came from; the
projects they were remixed or bought from — and the ones remixed or bought from them; what
of them is on the marketplace. Nothing here is new data: it is the provenance the platform
already writes, joined into nodes and edges a client can draw.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.core import Project
from app.models.execution import AIRequest
from app.models.marketplace import MarketplaceItem, MarketplaceOrder
from app.models.scanning import ScanSession
from app.models.versioning import ProjectVersion
from app.services import licensing, marketplace, projects
from app.services.authz import role_in_workspace

# What the provenance's `operation` means in words a maker reads.
OPERATIONS: dict[str, str] = {
    "ai_command": "built from words",
    "manual_edit": "edited",
    "import_model": "imported",
    "scan": "scanned",
    "remix": "remixed",
    "acquire": "from the marketplace",
    "split_model": "cut into parts",
    "paint_model": "painted",
    "rollback": "restored",
    "repair": "repaired",
    "optimize_print": "reoriented for printing",
    "execute_plan": "built from a plan",
    "convert_asset": "converted",
}


@dataclass
class Node:
    id: str
    kind: str  # version | command | scan | origin | listing | derived
    title: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "title": self.title, **self.data}


@dataclass
class Edge:
    source: str
    target: str
    kind: str  # parent | made_by | scanned | remixed_from | acquired_from | listed_as | derived

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "target": self.target, "kind": self.kind}


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    _ids: set[str] = field(default_factory=set)

    def add(self, node: Node) -> None:
        if node.id not in self._ids:
            self._ids.add(node.id)
            self.nodes.append(node)

    def link(self, source: str, target: str, kind: str) -> None:
        self.edges.append(Edge(source, target, kind))

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "summary": self.summary,
        }


def _visible_project(db: Session, user_id: uuid.UUID, project_id: uuid.UUID) -> Project | None:
    """The project when the user may see it; None for a stranger's — its name is theirs."""
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        return None
    if role_in_workspace(db, user_id, project.workspace_id) is None:
        return None
    return project


def graph(db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID) -> Graph:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    versions = list(
        db.scalars(
            sa.select(ProjectVersion)
            .where(ProjectVersion.project_id == project.id)
            .order_by(ProjectVersion.sequence_no)
        )
    )
    result = Graph()
    counts: dict[str, int] = {}

    for version in versions:
        provenance = version.provenance or {}
        operation = str(
            provenance.get("operation")
            or ("ai_command" if provenance.get("ai_request_id") else "created")
        )
        counts[operation] = counts.get(operation, 0) + 1
        vid = f"version:{version.id}"
        result.add(
            Node(
                vid,
                "version",
                version.label or f"v{version.sequence_no}",
                {
                    "version_id": str(version.id),
                    "sequence_no": version.sequence_no,
                    "state": version.state.value,
                    "operation": operation,
                    "operation_label": OPERATIONS.get(operation, operation),
                    "head": project.head_version_id == version.id,
                    "created_at": version.created_at.isoformat(),
                    "bodies": [
                        {"name": b.get("name"), "volume_mm3": b.get("volume_mm3")}
                        for b in (provenance.get("bodies") or [])
                        if isinstance(b, dict)
                    ][-1:],
                },
            )
        )
        if version.parent_version_id is not None:
            result.link(f"version:{version.parent_version_id}", vid, "parent")

        # the words that made it
        request_id = provenance.get("ai_request_id")
        if request_id:
            request = db.get(AIRequest, uuid.UUID(str(request_id)))
            if request is not None:
                cid = f"command:{request.id}"
                result.add(
                    Node(
                        cid,
                        "command",
                        request.prompt[:120],
                        {
                            "ai_request_id": str(request.id),
                            "status": request.status.value,
                            "cost_usd": str(request.cost_usd or 0),
                            "photos": len((request.context or {}).get("photos", [])),
                        },
                    )
                )
                result.link(cid, vid, "made_by")

        # the scan it came from
        scan_id = provenance.get("scan_session_id")
        if scan_id:
            scan = db.get(ScanSession, uuid.UUID(str(scan_id)))
            if scan is not None:
                sid = f"scan:{scan.id}"
                device = (scan.capabilities or {}).get("device") or {}
                device_name = f"{device.get('vendor', '')} {device.get('model', '')}".strip()
                report = scan.report or {}
                result.add(
                    Node(
                        sid,
                        "scan",
                        scan.label or "scan",
                        {
                            "scan_session_id": str(scan.id),
                            "mode": scan.mode.value,
                            "device": device_name or None,
                            "frames": scan.frame_count,
                            "scale": report.get("scale"),
                        },
                    )
                )
                result.link(sid, vid, "scanned")

        # where a remix or a marketplace copy came from
        for key, kind in (
            ("remixed_from_project_id", "remixed_from"),
            ("listing_id", "acquired_from"),
        ):
            reference = provenance.get(key)
            if not reference:
                continue
            if kind == "remixed_from":
                origin = _visible_project(db, user_id, uuid.UUID(str(reference)))
                oid = f"project:{reference}"
                result.add(
                    Node(
                        oid,
                        "origin",
                        origin.name if origin else "another maker's project",
                        {
                            "project_id": str(reference) if origin else None,
                            "visible": origin is not None,
                            "licence": licensing.licence_of(origin).name if origin else None,
                        },
                    )
                )
                result.link(oid, vid, kind)
            else:
                item = db.get(MarketplaceItem, uuid.UUID(str(reference)))
                oid = f"listing:{reference}"
                creator = marketplace.ensure_profile(db, item.creator_user_id) if item else None
                result.add(
                    Node(
                        oid,
                        "origin",
                        item.title if item else "a marketplace listing",
                        {
                            "listing_id": str(reference),
                            "creator_handle": creator.handle if creator else None,
                            "licence": licensing.LICENCES[item.license_id].name
                            if item and item.license_id in licensing.LICENCES
                            else None,
                        },
                    )
                )
                result.link(oid, vid, kind)

        # what of it is on the shelf, and how often it was taken
        listing = db.scalar(
            sa.select(MarketplaceItem).where(MarketplaceItem.version_id == version.id)
        )
        if listing is not None:
            lid = f"listing:{listing.id}"
            result.add(
                Node(
                    lid,
                    "listing",
                    listing.title,
                    {
                        "listing_id": str(listing.id),
                        "status": listing.status,
                        "price_cents": listing.price_cents,
                        "currency": listing.currency,
                        "downloads": listing.downloads,
                        "licence": licensing.LICENCES[listing.license_id].name
                        if listing.license_id in licensing.LICENCES
                        else listing.license_id,
                    },
                )
            )
            result.link(vid, lid, "listed_as")
            orders = list(
                db.scalars(
                    sa.select(MarketplaceOrder).where(MarketplaceOrder.item_id == listing.id)
                )
            )
            for order in orders:
                copy = _visible_project(db, user_id, order.project_id) if order.project_id else None
                did = f"project:{order.project_id or order.id}"
                result.add(
                    Node(
                        did,
                        "derived",
                        copy.name if copy else "taken by another maker",
                        {"project_id": str(copy.id) if copy else None, "visible": copy is not None},
                    )
                )
                result.link(lid, did, "derived")

    # projects that remixed this one, in workspaces the user can see
    remixes = list(
        db.scalars(
            sa.select(Project).where(
                Project.remixed_from_project_id == project.id, Project.deleted_at.is_(None)
            )
        )
    )
    for remix in remixes:
        if role_in_workspace(db, user_id, remix.workspace_id) is None:
            continue
        head = f"version:{project.head_version_id}" if project.head_version_id else None
        did = f"project:{remix.id}"
        if remix.remixed_from_project_id == project.id and did not in result._ids:
            result.add(
                Node(
                    did,
                    "derived",
                    remix.name,
                    {"project_id": str(remix.id), "visible": True, "remix": True},
                )
            )
            if head:
                result.link(head, did, "derived")

    terms = licensing.permissions(db, project)
    result.summary = {
        "versions": len(versions),
        "operations": counts,
        "licence": terms["licence"],
        "credits": terms["credits"],
        "remixed_from_project_id": (
            str(project.remixed_from_project_id) if project.remixed_from_project_id else None
        ),
    }
    return result
