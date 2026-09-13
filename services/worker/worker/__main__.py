"""Worker entrypoint placeholder; the job loop lands with the first async endpoint (T-031)."""

import sys

from worker import sandbox

if __name__ == "__main__":
    print(f"physical-ai-worker: sandbox network isolation={sandbox._unshare_available()}")
    sys.exit(0)
