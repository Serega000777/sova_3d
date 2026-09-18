"""T-098 — onboarding demo: a sentence becomes an editable, printable model.

Runs the path a brand-new user takes, against a running stack, and prints what they would
see at each step:

    docker compose -f infra/docker-compose.yml up -d
    python demos/organizer_from_text.py

With no arguments it creates a fresh user and workspace through the API container's CLI,
so "new user" means new. Pass --token/--workspace to use an existing one.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE = "http://localhost:18000/api/v1"
PROMPT = "Органайзер 200×100×50 мм с 6 секциями, скругление 1.5 мм"


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
    """Run the API container's CLI so the demo starts from nothing."""
    print("• creating a new user and workspace…")
    result = subprocess.run(
        [
            "docker", "compose", "-f", compose_file, "exec", "-T", "api",
            "uv", "run", "--no-sync", "python", "-m", "app.cli", "create-user",
            "--email", f"demo-{int(time.time())}@example.com",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"create-user failed: {result.stderr.strip() or result.stdout.strip()}")
    token = workspace = ""
    for line in (result.stdout + result.stderr).splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "token":
            token = value.strip()
        if key.strip() in ("workspace_id", "workspace"):
            workspace = value.strip()
    if not token or not workspace:
        raise SystemExit(f"could not read the new credentials from:\n{result.stdout}")
    print(f"  workspace {workspace}")
    return token, workspace


def wait(api: Api, job_id: str, label: str) -> dict[str, Any]:
    deadline = time.time() + 300
    last = ""
    while time.time() < deadline:
        job = api("GET", f"/jobs/{job_id}")
        stage = f"{job['progress']}% {job.get('stage') or ''}".strip()
        if stage != last:
            print(f"  {label}: {stage}")
            last = stage
        if job["status"] in ("succeeded", "failed", "canceled", "waiting_input"):
            return job
        time.sleep(1)
    raise SystemExit(f"{label} did not finish in time")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--token")
    parser.add_argument("--workspace")
    parser.add_argument("--prompt", default=PROMPT)
    parser.add_argument("--compose-file", default="infra/docker-compose.yml")
    args = parser.parse_args()

    token, workspace = (args.token, args.workspace)
    if not (token and workspace):
        token, workspace = create_user(args.compose_file)
    api = Api(args.base, token)

    print("• creating a project")
    project = api("POST", "/projects", {"workspace_id": workspace, "name": "Desk organizer"})

    print(f"• asking for: {args.prompt}")
    accepted = api(
        "POST",
        f"/projects/{project['id']}/ai-commands",
        {"prompt": args.prompt, "units": "mm", "target": "print"},
    )
    job = wait(api, accepted["job_id"], "planning & building")

    while job["status"] == "waiting_input":
        request = api("GET", f"/ai-requests/{accepted['ai_request_id']}")
        print("• the planner needs to know:")
        for question in request["clarifications"]:
            print(f"    {question}")
        answer = input("  your answer: ").strip()
        accepted = api("POST", f"/ai-requests/{request['id']}/clarify", {"answers": [answer]})
        job = wait(api, accepted["job_id"], "planning & building")

    if job["status"] != "succeeded":
        raise SystemExit(f"the command failed: {job.get('error')}")

    plan = job["result"]["plan"]
    body = job["result"]["bodies"][-1]
    size = body["bbox_mm"]["size"]
    print(f"• built {len(plan['operations'])} operations -> body '{body['name']}'")
    print(f"  {size[0]:.1f} × {size[1]:.1f} × {size[2]:.1f} mm, {body['volume_mm3']:.0f} mm³")
    for assumption in plan.get("assumptions", []):
        print(f"  assumption: {assumption}")

    version_id = job["result"]["version_id"]

    print("• editing it by the numbers: 180 mm wide")
    edit = api(
        "POST",
        f"/models/{version_id}/edits",
        {
            "operations": [
                {"type": "set_dimensions", "target": body["name"], "width_mm": 180}
            ],
            "label": "Resize to 180 mm",
        },
    )
    edited = wait(api, edit["job_id"], "resizing")
    if edited["status"] != "succeeded":
        raise SystemExit(f"the edit failed: {edited.get('error')}")
    version_id = edited["result"]["version_id"]
    print(f"  version {edited['result']['version_id']} — the original is still there")

    print("• checking whether it prints")
    analysis = api("POST", f"/models/{version_id}/analyze-print", {})
    checked = wait(api, analysis["job_id"], "print check")
    if checked["status"] == "succeeded":
        report = api("GET", f"/models/{version_id}/print-analyses")[0]["report"]
        score = report["score"]
        print(f"  {score['total']:.0f}/100 ({score['status']}) — {report['summary']}")
        for warning in report.get("warnings", []):
            print(f"    {warning['severity']}: {warning['message']}")

    print("• exporting STL")
    export = api("POST", f"/models/{version_id}/exports", {"format": "stl", "printable": True})
    exported = wait(api, export["job_id"], "export")
    if exported["status"] != "succeeded":
        raise SystemExit(f"the export failed: {exported.get('error')}")
    download = api("GET", f"/assets/{exported['result']['asset_id']}/download")
    with urllib.request.urlopen(download["url"], timeout=120) as response:
        stl = response.read()
    print(f"  {len(stl)} bytes of printable STL")

    versions = api("GET", f"/projects/{project['id']}/versions")
    print(f"\nDone. {len(versions)} versions, every one still openable:")
    for version in versions:
        print(f"  v{version['sequence_no']}  {version['label']}")
    print(f"\nOpen it in the web app: http://localhost:3100/projects/{project['id']}")
    print(f"Token: {token}\nWorkspace: {workspace}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
