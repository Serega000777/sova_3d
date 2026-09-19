"""The bridge streams what a driver delivers and hands the session over — with a fake API."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import trimesh

from physical_ai_scanner.bridge import run_scan
from physical_ai_scanner.client import ApiError, ScanClient
from physical_ai_scanner.drivers import driver_for
from physical_ai_scanner.drivers.folder import FolderScanner
from physical_ai_scanner.drivers.simulated import SimulatedScanner, bracket


class FakePlatform:
    """Just enough of the API for the bridge: uploads, one session, one job."""

    def __init__(self, *, fail_reconstruction: bool = False) -> None:
        self.uploads: list[tuple[str, bytes]] = []
        self.frames: list[dict[str, Any]] = []
        self.stats: dict[str, Any] = {}
        self.finalized = False
        self.accepted: dict[str, Any] | None = None
        self.canceled = False
        self.projects_made: list[str] = []
        self.fail_reconstruction = fail_reconstruction

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        payload = (
            json.loads(body) if body and headers.get("Content-Type") == "application/json" else {}
        )
        if path == "api/v1/uploads":
            return 201, json.dumps(
                {"upload_id": f"up{len(self.uploads)}", "url": "http://s3/put", "headers": {}}
            ).encode()
        if url == "http://s3/put":
            self.uploads.append((headers["Content-Type"], body or b""))
            return 200, b""
        if path == "api/v1/assets/complete":
            return 201, json.dumps({"id": f"asset-{len(self.uploads)}"}).encode()
        if path == "api/v1/scans" and method == "POST":
            assert (
                payload["mode"] == "scanner"
                and payload["capabilities"]["device"]["kind"] == "scanner"
            )
            return 201, json.dumps({"id": "scan-1", "status": "capturing"}).encode()
        if path == "api/v1/scans/scan-1/frames":
            self.frames.append(payload)
            return 201, json.dumps({"id": f"frame-{len(self.frames)}"}).encode()
        if path == "api/v1/scans/scan-1/capture-stats":
            self.stats = payload["stats"]
            return 200, json.dumps({"id": "scan-1"}).encode()
        if path == "api/v1/scans/scan-1/finalize":
            self.finalized = True
            return 202, json.dumps(
                {"job_id": "job-1", "status": "queued", "type": "reconstruct_scan"}
            ).encode()
        if path == "api/v1/jobs/job-1":
            if self.fail_reconstruction:
                return 200, json.dumps(
                    {"status": "failed", "error": {"message": "nothing fused"}}
                ).encode()
            return 200, json.dumps({"status": "succeeded"}).encode()
        if path == "api/v1/scans/scan-1" and method == "GET":
            report = {
                "provider": "fusion",
                "scale": {"applied_mm": 120.0, "source": "device", "confidence": 0.98},
            }
            return 200, json.dumps({"id": "scan-1", "status": "ready", "report": report}).encode()
        if path == "api/v1/scans/scan-1/accept":
            self.accepted = payload
            return 200, json.dumps(
                {"status": "accepted", "result_version_id": "ver-1", "project_id": "proj-1"}
            ).encode()
        if path == "api/v1/scans/scan-1/cancel":
            self.canceled = True
            return 200, json.dumps({"status": "canceled"}).encode()
        if path == "api/v1/projects" and method == "POST":
            self.projects_made.append(payload["name"])
            return 201, json.dumps({"id": "proj-new"}).encode()
        return 404, json.dumps({"error": {"code": "not_found", "message": path}}).encode()


def test_the_simulated_scanner_delivers_metric_shells_around_the_object() -> None:
    driver = SimulatedScanner(steps=6, noise=True)
    info = driver.open()
    assert info.turntable and info.to_dict()["kind"] == "scanner"
    fragments = list(driver.fragments())
    assert len(fragments) == 7  # six angles and one speck of dust
    for fragment in fragments[:6]:
        piece = trimesh.load(io.BytesIO(fragment.data), file_type="ply", force="mesh")
        assert isinstance(piece, trimesh.Trimesh)
        assert len(piece.faces) > 0 and fragment.kind == "mesh"
        assert "azimuth_deg" in fragment.pose and "turntable_centre_mm" in fragment.pose
        assert fragment.content_type == "model/ply"
    assert bracket().extents.tolist() == [120.0, 60.0, 40.0]


def test_the_folder_driver_picks_up_files_as_they_appear(tmp_path: Path) -> None:
    (tmp_path / "old.stl").write_bytes(trimesh.creation.box().export(file_type="stl"))
    driver = FolderScanner(str(tmp_path), idle_s=0.2, settle_s=0.01, poll_s=0.01, fresh_only=True)
    driver.open()
    piece = trimesh.creation.icosphere(subdivisions=1, radius=5)
    (tmp_path / "part_01.ply").write_bytes(piece.export(file_type="ply"))
    (tmp_path / "part_01.ply.json").write_text(json.dumps({"azimuth_deg": 45}), encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a fragment", encoding="utf-8")
    fragments = list(driver.fragments())
    assert [f.filename for f in fragments] == [
        "part_01.ply"
    ]  # the old file and the note are skipped
    assert fragments[0].pose == {"azimuth_deg": 45} and fragments[0].content_type == "model/ply"


def test_the_bridge_streams_reconstructs_and_accepts() -> None:
    platform = FakePlatform()
    client = ScanClient("http://api", "pai_test", transport=platform)
    lines: list[str] = []
    result = run_scan(
        client,
        driver_for("simulated", steps=4, noise=False),
        workspace_id="ws-1",
        label="bracket",
        project_id="proj-1",
        log=lines.append,
    )
    assert result.fragments == 4 and len(platform.uploads) == 4
    assert [f["sequence_no"] for f in platform.frames] == [0, 1, 2, 3]
    assert all(f["kind"] == "mesh" and "azimuth_deg" in f["pose"] for f in platform.frames)
    assert platform.stats["fragments"] == 4 and platform.finalized
    assert platform.accepted == {"label": "bracket", "project_id": "proj-1"}
    assert result.status == "accepted" and result.version_id == "ver-1"
    assert result.report["scale"]["source"] == "device"
    assert any("model ready: 120.0 mm across" in line for line in lines)


def test_a_scan_without_a_project_gets_one_named_after_it() -> None:
    platform = FakePlatform()
    client = ScanClient("http://api", "pai_test", transport=platform)
    result = run_scan(
        client,
        driver_for("simulated", steps=3, noise=False),
        workspace_id="ws-1",
        label="bumper",
        log=lambda _: None,
    )
    assert platform.projects_made == ["bumper"]
    assert platform.accepted == {"label": "bumper", "project_id": "proj-new"}
    assert result.status == "accepted"


def test_a_failed_reconstruction_is_reported_not_hidden() -> None:
    platform = FakePlatform(fail_reconstruction=True)
    client = ScanClient("http://api", "pai_test", transport=platform)
    result = run_scan(
        client,
        driver_for("simulated", steps=3, noise=False),
        workspace_id="ws-1",
        log=lambda _: None,
    )
    assert result.status == "failed" and result.error == "nothing fused"
    assert platform.accepted is None


def test_an_empty_folder_cancels_the_session(tmp_path: Path) -> None:
    platform = FakePlatform()
    client = ScanClient("http://api", "pai_test", transport=platform)
    driver = FolderScanner(str(tmp_path), idle_s=0.05, poll_s=0.01)
    result = run_scan(client, driver, workspace_id="ws-1", log=lambda _: None)
    assert result.status == "canceled" and platform.canceled


def test_api_errors_carry_the_platforms_message() -> None:
    def transport(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        return 402, json.dumps(
            {"error": {"code": "ai_quota_exceeded", "message": "budget spent"}}
        ).encode()

    client = ScanClient("http://api", "pai_test", transport=transport)
    try:
        client.create_session("ws", device={})
    except ApiError as exc:
        assert (
            exc.status == 402 and exc.code == "ai_quota_exceeded" and exc.message == "budget spent"
        )
    else:
        raise AssertionError("expected ApiError")
