"""Sandbox entry point for real slicing (perimeters, infill, G-code) of an untrusted STL."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from worker import gcode
from worker.printcheck import PrinterProfile


def main(args: list[str]) -> int:
    if len(args) != 3:
        print(json.dumps({"ok": False, "message": "expected mesh, config and output dir"}))
        return 2
    try:
        config = json.loads(Path(args[1]).read_text(encoding="utf-8"))
        printer = PrinterProfile.model_validate(config["printer"])
        settings = gcode.SliceSettings.model_validate(config["settings"])
        stats = gcode.slice_to_file(gcode.load_stl(Path(args[0])), printer, settings, Path(args[2]))
        print(json.dumps({"ok": True, "stats": stats.model_dump()}))
    except (ValueError, TypeError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "message": str(exc)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
