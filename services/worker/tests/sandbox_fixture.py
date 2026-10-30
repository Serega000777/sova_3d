"""Misbehaving child programs for the sandbox tests.

Run as `python -m tests.sandbox_fixture MODE`.
"""

import json
import os
import socket
import subprocess
import sys
import time


def main(mode: str, *args: str) -> None:
    if mode == "ok":
        secrets = [k for k in os.environ if "SECRET" in k or k.startswith("AWS_")]
        print(json.dumps({"answer": 42, "env_scrubbed": not secrets}))
    elif mode == "sleep":
        time.sleep(30)
    elif mode == "crash":
        print("boom", file=sys.stderr)
        sys.exit(3)
    elif mode == "garbage":
        print("this is not json")
    elif mode == "flood":
        print(json.dumps({"blob": "x" * 4096}))
    elif mode == "allocate":
        chunks = []
        for _ in range(64):
            chunks.append(bytearray(64 * 1024 * 1024))  # 4 GB total if allowed
        print(json.dumps({"allocated_mb": 64 * len(chunks)}))
    elif mode == "spin":
        deadline = time.time() + 30
        x = 0
        while time.time() < deadline:
            x += 1
        print(json.dumps({"iterations": x}))
    elif mode == "network":
        try:
            with socket.create_connection(("1.1.1.1", 53), timeout=3):
                connected = True
        except OSError:
            connected = False
        print(json.dumps({"connected": connected}))
    elif mode == "descendant":
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
            ]
        )
        with open(args[0], "w", encoding="utf-8") as handle:
            handle.write(str(child.pid))
        time.sleep(30)
    elif mode == "write_file":
        with open(args[0], "wb") as handle:
            handle.write(b"x" * 4096)
        print(json.dumps({"written": True}))
    else:
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1], *sys.argv[2:])
