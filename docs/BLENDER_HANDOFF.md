# Safe Blender handoff

Sova can package one finalized immutable model version as an editable `.blend` export:

```http
POST /api/v1/models/{version_id}/blender-handoffs
Idempotency-Key: stable-client-key

{"operation":"editable_scene"}
```

The endpoint returns a durable `JobAccepted`. On success the job result contains a `blend`
`asset_id`; the normal authorized `GET /api/v1/assets/{asset_id}/download` route supplies its
short-lived URL. The source version is not changed.

## Fixed contract

- The caller can select only `editable_scene`. Python, add-ons, filenames, paths, shell text,
  Blender switches and render settings are not accepted.
- Only a finalized version and its server-resolved canonical model/painted preview are used.
- Multi-object Sova scenes fail closed for now instead of being flattened silently.
- Sova first produces and validates a GLB, then passes only that GLB to Blender.
- The result is attached as an immutable content-addressed export with source-version lineage,
  input hash, Blender/script versions, license snapshot and a strict report.

## Isolation boundary

Blender never runs directly in the API process or the credentialed job worker. The job worker
copies only a validated GLB into a private spool volume. A dedicated `blender-runner` sidecar has
no application env file, no DB/S3/Redis credentials and `network_mode: none`; only that minimal
sidecar receives the namespace capability needed by the trusted launcher. It requires all of the
following and fails before Blender launch when any boundary is unavailable:

1. the existing scrubbed child environment and CPU/memory/file/wall-clock limits;
2. a mandatory network namespace created by `unshare`;
3. a `bubblewrap` mount/PID/IPC/UTS/cgroup namespace exposing read-only `/usr`, the fixed bundled
   script and one private `/work` directory only;
4. Blender UID/GID `65534`, zero effective/permitted/ambient capabilities and
   `no-new-privileges`;
5. `--factory-startup --background --disable-autoexec --python-exit-code` with the bundled script;
6. rejection of scripts, drivers, external libraries, unpacked resources, non-finite/extreme
   transforms and bounded object/geometry/texture limits;
7. a second isolated Blender invocation that reopens the `.blend` and must reproduce the same
   strict report;
8. `O_NOFOLLOW`, regular-file/link-count, size, magic, hash and unexpected-file checks before the
   artifact leaves the private directory.

The main worker keeps Docker's default capability, AppArmor and seccomp boundaries. Only the
secretless, networkless, read-only-root `blender-runner` relaxes the profiles required to create
nested namespaces. The untrusted Blender process itself sees neither the main worker filesystem
nor its network, parent `/proc`, `/app`, credentials or capabilities.

## Honest boundary

This increment produces a downloadable, verified `.blend` handoff. It does not remotely control a
desktop Blender installation, install an add-on, accept arbitrary Blender automation, or preserve a
Sova multi-object scene as separate Blender objects. Those remain separate client/scene contracts.
