"""T-100 — end-to-end demo: a model, validated, exported and downloaded.

    docker compose -f infra/docker-compose.yml up -d
    python demos/export_validated.py

Builds a part, repairs the mesh, checks printability, then exports every supported format
with the printable gate on and downloads each file. The gate is the point: an export that
would not print is refused rather than handed over.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE = "http://localhost:18000/api/v1"
PROMPT = "Bracket 60x40x8 mm with 2 holes 5 mm, fillet 2 mm"


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


def create_user(compose_file: str) -> tuple[str, str]:
    print("• creating a new user and workspace…")
    result = subprocess.run(
        [
            "docker", "compose", "-f", compose_file, "exec", "-T", "api",
            "uv", "run", "--no-sync", "python", "-m", "app.cli", "create-user",
            "--email", f"export-demo-{int(time.time())}@example.com",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"create-user failed: {result.stderr.strip() or result.stdout.strip()}")
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    token, workspace = values.get("token", "").strip(), values.get("workspace_id", "").strip()
    if not token or not workspace:
        raise SystemExit(f"could not read the new credentials from:\n{result.stdout}")
    return token, workspace


def wait(api: Api, job_id: str, label: str) -> dict[str, Any]:
    deadline = time.time() + 600
    while time.time() < deadline:
        job = api("GET", f"/jobs/{job_id}")
        if job["status"] in ("succeeded", "failed", "canceled", "waiting_input"):
            print(f"  {label}: {job['status']}")
            return job
        time.sleep(1)
    raise SystemExit(f"{label} did not finish in time")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--token")
    parser.add_argument("--workspace")
    parser.add_argument("--prompt", default=PROMPT)
    parser.add_argument("--out", default="demo-exports", help="where to save the files")
    parser.add_argument("--compose-file", default="infra/docker-compose.yml")
    args = parser.parse_args()

    token, workspace = (args.token, args.workspace)
    if not (token and workspace):
        token, workspace = create_user(args.compose_file)
    api = Api(args.base, token)

    project = api("POST", "/projects", {"workspace_id": workspace, "name": "Export demo"})
    print(f"• building: {args.prompt}")
    accepted = api(
        "POST",
        f"/projects/{project['id']}/ai-commands",
        {"prompt": args.prompt, "units": "mm", "target": "print"},
    )
    job = wait(api, accepted["job_id"], "build")
    if job["status"] != "succeeded":
        raise SystemExit(f"the build failed: {job.get('error')}")
    version_id = job["result"]["version_id"]
    body = job["result"]["bodies"][-1]
    print(f"  body '{body['name']}' valid={body['valid']} volume={body['volume_mm3']:.0f} mm³")

    print("• repairing the mesh (a no-op on a clean kernel body, and it says so)")
    repair = api("POST", f"/models/{version_id}/repair")
    repaired = wait(api, repair["job_id"], "repair")
    if repaired["status"] == "succeeded":
        report = repaired["result"]["report"]
        after = report["after"]
        print(f"  watertight={after['watertight']} holes={after['holes']} faces={after['faces']}")
        version_id = repaired["result"]["version_id"]

    print("• checking printability")
    analysis = api("POST", f"/models/{version_id}/analyze-print", {})
    checked = wait(api, analysis["job_id"], "print check")
    if checked["status"] == "succeeded":
        printability = api("GET", f"/models/{version_id}/print-analyses")[0]["report"]
        score = printability["score"]
        print(f"  {score['total']:.0f}/100 ({score['status']}) — {printability['summary']}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for fmt in ("stl", "3mf", "glb"):
        printable = fmt != "glb"  # glTF is for looking at, not for printing
        export = api(
            "POST", f"/models/{version_id}/exports", {"format": fmt, "printable": printable}
        )
        finished = wait(api, export["job_id"], f"export {fmt}")
        if finished["status"] != "succeeded":
            print(f"  {fmt}: refused — {finished.get('error', {}).get('message')}")
            continue
        download = api("GET", f"/assets/{finished['result']['asset_id']}/download")
        with urllib.request.urlopen(download["url"], timeout=120) as response:
            data = response.read()
        target = out / f"bracket.{fmt}"
        target.write_bytes(data)
        gate = "printable gate on" if printable else "view only"
        print(f"  {target} — {len(data)} bytes ({gate})")

    print(f"\nDone. Files in {out.resolve()}")
    print(f"Open the project: http://localhost:3100/projects/{project['id']}")
    print(f"Token: {token}\nWorkspace: {workspace}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
