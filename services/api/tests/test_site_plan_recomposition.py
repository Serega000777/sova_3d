from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.api.errors import ValidationFailedError
from app.models.versioning import ProjectVersion
from app.services.scenes import IDENTITY, SCENE_SCHEMA_VERSION
from app.services.site_plans import base_house_nodes


def _node(node_id: str, kind: str, parent_id: str | None) -> dict[str, object]:
    return {
        "id": node_id,
        "name": node_id,
        "kind": kind,
        "parent_id": parent_id,
        "visible": True,
        "transform": IDENTITY,
        "asset_id": None if kind == "group" else "00000000-0000-0000-0000-000000000001",
        "instance_of": None,
    }


def _version(nodes: list[dict[str, object]]) -> ProjectVersion:
    return cast(
        ProjectVersion,
        cast(
            Any,
            SimpleNamespace(
                provenance={
                    "site_plan": {"schema_version": 1},
                    "scene": {"schema_version": SCENE_SCHEMA_VERSION, "nodes": nodes},
                },
                assets=[],
            ),
        ),
    )


def _canonical_nodes() -> list[dict[str, object]]:
    return [
        _node("site_root", "group", None),
        _node("site_house", "group", "site_root"),
        _node("house_group", "group", "site_house"),
        _node("house_model", "object", "house_group"),
        _node("site_terrain", "object", "site_root"),
        _node("site_house_pad", "object", "site_root"),
        _node("site_path", "object", "site_root"),
        _node("site_fence", "object", "site_root"),
    ]


def test_recomposition_unwraps_only_the_canonical_house_subtree() -> None:
    nodes = base_house_nodes(_version(_canonical_nodes()))
    assert [node["id"] for node in nodes] == ["house_group", "house_model"]
    assert nodes[0]["parent_id"] is None
    assert nodes[1]["parent_id"] == "house_group"


def test_recomposition_refuses_to_drop_a_buyer_added_sibling() -> None:
    nodes = [*_canonical_nodes(), _node("buyer_gazebo", "object", "site_root")]
    with pytest.raises(ValidationFailedError, match="remove added site objects"):
        base_house_nodes(_version(nodes))
