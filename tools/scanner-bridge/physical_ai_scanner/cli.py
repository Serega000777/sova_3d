"""`physical-ai-scanner scan …` — from the scanner on the desk to a project in the workspace.

    physical-ai-scanner scan --api http://localhost:18000 --token pai_… --workspace <id> \\
        --driver folder --path "C:/Users/me/Documents/Revo Scan/exports" --label "bumper"

    physical-ai-scanner scan … --driver simulated --steps 8          # no hardware
    physical-ai-scanner scan … --driver realsense --steps 12         # Intel RealSense
"""

from __future__ import annotations

import argparse
import os
import sys

from physical_ai_scanner import __version__
from physical_ai_scanner.bridge import run_scan
from physical_ai_scanner.client import ApiError, ScanClient
from physical_ai_scanner.drivers import driver_for


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="physical-ai-scanner")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    scan = commands.add_parser("scan", help="stream a scan into the platform")
    scan.add_argument("--api", default=os.environ.get("PHYSICAL_AI_API", "http://localhost:18000"))
    scan.add_argument("--token", default=os.environ.get("PHYSICAL_AI_TOKEN"))
    scan.add_argument("--workspace", default=os.environ.get("PHYSICAL_AI_WORKSPACE"))
    scan.add_argument("--driver", default="folder", choices=["folder", "simulated", "realsense"])
    scan.add_argument("--label", default=None, help="what is being scanned")
    scan.add_argument("--project", default=None, help="add the scan to this project")
    scan.add_argument("--no-accept", action="store_true", help="reconstruct, but do not add it")
    # folder
    scan.add_argument("--path", default=None, help="folder the scanner software saves into")
    scan.add_argument("--idle", type=float, default=20.0, help="seconds without a new file = done")
    scan.add_argument("--fresh-only", action="store_true", help="ignore files already there")
    # simulated / realsense
    scan.add_argument("--steps", type=int, default=8, help="turntable steps")
    scan.add_argument("--delay", type=float, default=0.0, help="simulated seconds per step")
    scan.add_argument("--range-mm", type=float, default=600.0, help="realsense depth clip")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.token or not args.workspace:
        print("a token and a workspace are required (--token/--workspace or env)", file=sys.stderr)
        return 2
    options: dict[str, object] = {}
    if args.driver == "folder":
        if not args.path:
            print("--path is required for the folder driver", file=sys.stderr)
            return 2
        options = {"path": args.path, "idle_s": args.idle, "fresh_only": args.fresh_only}
    elif args.driver == "simulated":
        options = {"steps": args.steps, "delay_s": args.delay}
    elif args.driver == "realsense":
        options = {"steps": args.steps, "range_mm": args.range_mm}
    try:
        driver = driver_for(args.driver, **options)
        result = run_scan(
            ScanClient(args.api, args.token),
            driver,
            workspace_id=args.workspace,
            label=args.label,
            project_id=args.project,
            accept=not args.no_accept,
        )
    except (ApiError, RuntimeError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if result.error:
        return 1
    if result.project_id:
        print(f"open it: {args.api.replace(':18000', ':3100')}/projects/{result.project_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
