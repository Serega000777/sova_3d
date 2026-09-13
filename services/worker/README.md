# services/worker

General worker: sandboxed parsing of untrusted model files, mesh diagnostics,
conversions and exports. Python 3.13, managed with uv.

```bash
uv sync
uv run pytest            # rlimit/network-isolation tests are POSIX-only (skipped on Windows)
uv run ruff check .
uv run mypy worker tests
```

## Sandbox (T-017)

`worker.sandbox.run(module, args, input_path=..., limits=...)` executes a parser
in a child interpreter with a scrubbed environment (no cloud credentials),
wall-clock timeout, CPU/memory rlimits, an input-size gate and a stdout cap.
The child must print one JSON object; anything else becomes a structured
`SandboxResult` failure.

Network isolation uses an unprivileged network namespace (`unshare -rn`).
Inside Docker this needs user namespaces, which the default seccomp profile
blocks: run the worker container with `cap_add: [SYS_ADMIN]` (see
`infra/docker-compose.yml`) or a custom seccomp profile. Without it the runner
falls back to "no isolation" and reports so at startup. Production hardening
options beyond MVP: gVisor/Firecracker runtime, or a dedicated converter pool
whose containers have no network at all.

```bash
docker build -t physical-ai-worker .
docker run --rm --cap-add SYS_ADMIN physical-ai-worker uv run --no-sync pytest -q
```
