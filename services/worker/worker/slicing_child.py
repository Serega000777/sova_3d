"""Sandbox entry point for cross-section preview of an untrusted STL."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from worker import slicing
from worker.printcheck import PrinterProfile


def main(args: list[str]) -> int:
    if len(args) != 2:
        print(json.dumps({"ok": False, "message": "expected mesh and printer profile"}))
        return 2
    try:
        printer = PrinterProfile.model_validate_json(Path(args[1]).read_text(encoding="utf-8"))
        result = slicing.preview(slicing.load_stl(Path(args[0])), printer)
        print(json.dumps({"ok": True, "preview": result}))
    except (ValueError, TypeError, OSError) as exc:
        print(json.dumps({"ok": False, "message": str(exc)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
