"""The lightweight API request contract must stay identical to the worker contract."""

from worker import meshedit as worker_mesh_edit

from app.geometry import mesh_edit as api_mesh_edit


def without_descriptions(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: without_descriptions(item) for key, item in value.items() if key != "description"
        }
    if isinstance(value, list):
        return [without_descriptions(item) for item in value]
    return value


def test_api_and_worker_mesh_edit_request_schemas_match() -> None:
    assert without_descriptions(
        api_mesh_edit.EditRequest.model_json_schema()
    ) == without_descriptions(worker_mesh_edit.EditRequest.model_json_schema())
