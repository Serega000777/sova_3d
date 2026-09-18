"""Record the printability golden file (T-094). Run from services/worker:

    uv run python tests/record_printcheck_golden.py

Review the diff: every number here is one a user reads off a screen.
"""

import json

from tests.test_printcheck_golden import FIXTURES, GOLDEN, snapshot
from worker import printcheck as pc


def main() -> None:
    fixtures = {name: snapshot(pc.analyze(make())) for name, make in sorted(FIXTURES.items())}
    analysis = pc.analyze(FIXTURES["clean_box"]())
    document = {
        "_comment": (
            "T-094: pinned printability scores. Regenerate with "
            "tests/record_printcheck_golden.py and explain any change in the commit."
        ),
        "_heuristics_version": analysis.heuristics_version,
        "_printer": "default profile (see worker/printcheck.py)",
        "fixtures": fixtures,
    }
    with open(GOLDEN, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"wrote {GOLDEN} ({len(fixtures)} fixtures)")


if __name__ == "__main__":
    main()
