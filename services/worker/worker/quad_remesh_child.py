"""Trusted launcher for Blender's QuadriFlow remesh inside a mandatory bubblewrap profile.

Mirrors `blender_handoff_child.py`'s isolation profile exactly; the only caller-controlled
value is `target_faces`, a bounded integer re-validated here and again inside the fixed
Blender script before it reaches `bpy.ops.object.quadriflow_remesh`.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

BWRAP = Path("/usr/bin/bwrap")
BLENDER = Path("/usr/bin/blender")
UNSHARE = Path("/usr/bin/unshare")
EXIT_ON_SCRIPT_ERROR = "73"
MIN_TARGET_FACES = 100
MAX_TARGET_FACES = 100_000
# QuadriFlow is documented to be slow on non-trivial geometry; the handoff's plain
# package/verify budget (135s) is too tight for it.
REMESH_TIMEOUT_SECONDS = 600
VERIFY_TIMEOUT_SECONDS = 135


def _runtime_mounts() -> list[str]:
    mounts = ["--ro-bind", "/usr", "/usr"]
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    local_dynload = Path(f"/usr/local/lib/python{python_version}/lib-dynload")
    blender_dynload = f"/usr/lib/python{python_version}/lib-dynload"
    mounts.extend(["--ro-bind", str(local_dynload), blender_dynload])
    for path in ("/bin", "/sbin", "/lib", "/lib64"):
        candidate = Path(path)
        if candidate.is_symlink():
            mounts.extend(["--symlink", os.readlink(candidate), path])
        elif candidate.exists():
            mounts.extend(["--ro-bind", path, path])
    mounts.extend(["--dir", "/etc"])
    for path in ("/etc/ld.so.cache", "/etc/fonts", "/etc/alternatives"):
        if Path(path).exists():
            mounts.extend(["--ro-bind", path, path])
    return mounts


def _command(workdir: Path, mode: str, target_faces: int) -> list[str]:
    script = Path(__file__).with_name("quad_remesh_script.py").resolve()
    return [
        str(UNSHARE),
        "--net",
        "--fork",
        "--kill-child=KILL",
        str(BWRAP),
        "--unshare-pid",
        "--unshare-uts",
        "--unshare-ipc",
        "--unshare-cgroup",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        *_runtime_mounts(),
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--chmod",
        "1777",
        "/tmp",
        "--dir",
        "/home",
        "--dir",
        "/home/blender",
        "--dir",
        "/runner",
        "--ro-bind",
        str(script),
        "/runner/quad_remesh_script.py",
        "--bind",
        str(workdir),
        "/work",
        "--chdir",
        "/work",
        "--setenv",
        "HOME",
        "/home/blender",
        "--setenv",
        "TMPDIR",
        "/tmp",
        "--setenv",
        "XDG_CONFIG_HOME",
        "/tmp/config",
        "--setenv",
        "XDG_CACHE_HOME",
        "/tmp/cache",
        "/usr/bin/setpriv",
        "--reuid=65534",
        "--regid=65534",
        "--clear-groups",
        "--no-new-privs",
        str(BLENDER),
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--python-exit-code",
        EXIT_ON_SCRIPT_ERROR,
        "--python",
        "/runner/quad_remesh_script.py",
        "--",
        mode,
        str(target_faces),
    ]


def _run(command: list[str], timeout: float) -> tuple[bool, str]:
    with tempfile.TemporaryFile() as output:
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
                env={"PATH": "/usr/bin:/bin"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)[:500]
        output.seek(0, os.SEEK_END)
        length = output.tell()
        output.seek(max(0, length - 5000))
        tail = output.read().decode("utf-8", "replace")
    return completed.returncode == 0, tail


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or os.environ.get("PHYSICAL_AI_SANDBOX") != "1":
        print(json.dumps({"ok": False, "code": "invalid_invocation"}))
        return 2
    workdir = Path(args[0]).resolve()
    if not args[1].isdecimal():
        print(json.dumps({"ok": False, "code": "invalid_target_faces"}))
        return 2
    target_faces = int(args[1])
    if not MIN_TARGET_FACES <= target_faces <= MAX_TARGET_FACES:
        print(json.dumps({"ok": False, "code": "invalid_target_faces"}))
        return 2
    info = workdir.lstat()
    if not stat.S_ISDIR(info.st_mode) or workdir != Path.cwd().resolve():
        print(json.dumps({"ok": False, "code": "invalid_workdir"}))
        return 2
    if not BWRAP.is_file() or not BLENDER.is_file() or not UNSHARE.is_file():
        print(json.dumps({"ok": False, "code": "isolation_unavailable"}))
        return 2
    if {entry.name for entry in workdir.iterdir()} != {"input.glb"}:
        print(json.dumps({"ok": False, "code": "unexpected_input"}))
        return 2
    if os.geteuid() != 0:
        print(json.dumps({"ok": False, "code": "isolation_unavailable"}))
        return 2
    os.chown(workdir, 65534, 65534)
    os.chown(workdir / "input.glb", 65534, 65534)
    workdir.chmod(0o700)
    (workdir / "input.glb").chmod(0o400)

    ok, message = _run(_command(workdir, "remesh", target_faces), REMESH_TIMEOUT_SECONDS)
    if not ok:
        print(json.dumps({"ok": False, "code": "blender_failed", "message": message}))
        return 2
    ok, message = _run(_command(workdir, "verify", target_faces), VERIFY_TIMEOUT_SECONDS)
    if not ok:
        print(json.dumps({"ok": False, "code": "verification_failed", "message": message}))
        return 2
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
