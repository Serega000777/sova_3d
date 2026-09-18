"""T-099 — onboarding demo: the mobile path, an object becomes a model.

Walks the whole scan flow against a running stack, exactly as the phone does it:

    docker compose -f infra/docker-compose.yml up -d
    python demos/scan_to_model.py

The frames here are generated images, so the demo runs with no camera. On a phone the same
calls are made by `apps/mobile/app/scan/index.tsx` — session, frames one at a time,
finalize, review, accept — and the pictures are real. The reconstruction provider is the
local stub unless one is configured, and the report says so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib
from typing import Any

DEFAULT_BASE = "http://localhost:18000/api/v1"
FRAMES = 18


class Api:
    def __init__(self, base: str, token: str) -> None:
        self.base = base.rstrip("/")
        self.token = token

    def __call__(self, method: str, path: str, body: Any = None) -> Any:
        url = path if path.startswith("http") else f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        if data:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode()[:500]
            raise SystemExit(f"{method} {url} failed with {error.code}: {detail}") from None
        return json.loads(payload) if payload else None


def frame_png(index: int, size: int = 96) -> bytes:
    """A frame that changes with the angle, so the upload is not the same file 18 times."""
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            row.extend(((index * 13 + x) % 256, (y * 5 + index * 7) % 256, (x * y) % 256))
        rows.append(bytes(row))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
        + chunk(b"IEND", b"")
    )


def create_user(compose_file: str) -> tuple[str, str]:
    print("• creating a new user and workspace…")
    result = subprocess.run(
        [
            "docker", "compose", "-f", compose_file, "exec", "-T", "api",
            "uv", "run", "--no-sync", "python", "-m", "app.cli", "create-user",
            "--email", f"scan-demo-{int(time.time())}@example.com",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"create-user failed: {result.stderr.strip() or result.stdout.strip()}")
    values = dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )
    token, workspace = values.get("token", "").strip(), values.get("workspace_id", "").strip()
    if not token or not workspace:
        raise SystemExit(f"could not read the new credentials from:\n{result.stdout}")
    return token, workspace


def upload_frame(api: Api, workspace: str, index: int) -> str:
    data = frame_png(index)
    upload = api(
        "POST",
        "/uploads",
        {
            "workspace_id": workspace,
            "filename": f"frame_{index:05d}.png",
            "content_type": "image/png",
            "byte_size": len(data),
        },
    )
    put = urllib.request.Request(upload["url"], data=data, method="PUT")
    put.add_header("Content-Type", "image/png")
    with urllib.request.urlopen(put, timeout=120) as response:
        if response.status not in (200, 204):
            raise SystemExit(f"frame {index} did not upload: {response.status}")
    asset = api(
        "POST",
        "/assets/complete",
        {"upload_id": upload["upload_id"], "sha256": hashlib.sha256(data).hexdigest()},
    )
    return str(asset["id"])


def wait(api: Api, job_id: str, label: str) -> dict[str, Any]:
    deadline = time.time() + 600
    last = ""
    while time.time() < deadline:
        job = api("GET", f"/jobs/{job_id}")
        stage = f"{job['progress']}% {job.get('stage') or ''}".strip()
        if stage != last:
            print(f"  {label}: {stage}")
            last = stage
        if job["status"] in ("succeeded", "failed", "canceled"):
            return job
        time.sleep(1)
    raise SystemExit(f"{label} did not finish in time")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--token")
    parser.add_argument("--workspace")
    parser.add_argument("--frames", type=int, default=FRAMES)
    parser.add_argument(
        "--size-mm",
        type=float,
        default=95.0,
        help="the object's largest dimension, if the user measured it",
    )
    parser.add_argument("--compose-file", default="infra/docker-compose.yml")
    args = parser.parse_args()

    token, workspace = (args.token, args.workspace)
    if not (token and workspace):
        token, workspace = create_user(args.compose_file)
    api = Api(args.base, token)

    project = api("POST", "/projects", {"workspace_id": workspace, "name": "Scanned objects"})
    scan = api(
        "POST",
        "/scans",
        {
            "workspace_id": workspace,
            "project_id": project["id"],
            "label": "mug",
            "mode": "rgb",
            "capabilities": {"runtime": "expo-go", "depth_scan": False},
        },
    )
    print(f"• scan session {scan['id']} ({scan['mode']}, no depth sensor)")

    print(f"• walking around the object: {args.frames} frames")
    for index in range(args.frames):
        asset_id = upload_frame(api, workspace, index)
        api(
            "POST",
            f"/scans/{scan['id']}/frames",
            {
                "asset_id": asset_id,
                "sequence_no": index,
                "pose": {"azimuth_deg": round(index * 360 / args.frames)},
                "quality": {"sharpness": 0.78, "steady": True},
            },
        )
        print(f"  frame {index + 1}/{args.frames}", end="\r")
    print()

    # Re-sending a frame is how a phone recovers from a dropped connection (T-078).
    api(
        "POST",
        f"/scans/{scan['id']}/frames",
        {"asset_id": asset_id, "sequence_no": args.frames - 1},
    )
    state = api("GET", f"/scans/{scan['id']}")
    print(f"  {state['frame_count']} frames stored (the re-sent one did not duplicate)")

    print("• reconstructing")
    accepted = api(
        "POST",
        f"/scans/{scan['id']}/finalize",
        {"scale_hint_mm": args.size_mm, "scale_confidence": 0.7},
    )
    job = wait(api, accepted["job_id"], "reconstruction")
    if job["status"] != "succeeded":
        raise SystemExit(f"reconstruction failed: {job.get('error')}")

    ready = api("GET", f"/scans/{scan['id']}")
    report = ready["report"]
    scale = report["scale"]
    print(f"  provider: {report['provider']}, coverage {report['coverage'] * 100:.0f}%")
    print(f"  size: {scale['applied_mm']} mm across, source '{scale['source']}', "
          f"confidence {scale['confidence']}")
    if scale.get("warning"):
        print(f"  ⚠ {scale['warning']}")
    repair = report.get("repair", {})
    if repair.get("after"):
        after = repair["after"]
        print(f"  cleanup: {after['faces']} faces, {after['holes']} holes, "
              f"watertight={after.get('watertight')}")
    if report.get("placeholder"):
        print(f"  note: {report['note']}")

    print("• the user looks at it and keeps it")
    kept = api("POST", f"/scans/{scan['id']}/accept", {"label": "Scanned mug"})
    version = api("GET", f"/versions/{kept['result_version_id']}")
    print(f"  version v{version['sequence_no']} '{version['label']}' ({version['state']})")

    print("• checking whether it prints")
    analysis = api("POST", f"/models/{version['id']}/analyze-print", {})
    checked = wait(api, analysis["job_id"], "print check")
    if checked["status"] == "succeeded":
        printability = api("GET", f"/models/{version['id']}/print-analyses")[0]["report"]
        print(f"  {printability['score']['total']:.0f}/100 "
              f"({printability['score']['status']}) — {printability['summary']}")

    print(f"\nDone. The scan is a normal project version now — editable, printable:")
    print(f"  http://localhost:3100/projects/{project['id']}")
    print(f"Token: {token}\nWorkspace: {workspace}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
