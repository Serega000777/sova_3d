# Safe Blender handoff

Sova can package a finalized immutable model or explicit multi-object scene version as an
editable `.blend` export:

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
- Only a finalized version and its server-resolved canonical model/painted preview or explicit
  immutable scene graph are used.
- Explicit scenes are resolved again inside the job with the same effective visibility and world
  transforms as canonical scene export. Hidden nodes are omitted; visible instances remain named,
  separate editable Blender mesh objects; trusted catalogue appearance metadata is preserved.
- The Blender report must contain exactly one mesh object per expected visible scene node. A
  flattened, dropped or extra object fails with `scene_structure_mismatch` instead of producing a
  misleading handoff.
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
3. a `bubblewrap` mount/PID/IPC/UTS/cgroup namespace exposing read-only `/usr`, only the matching
   compiled Python runtime directory needed by Blender, the fixed bundled script and one private
   `/work` directory;
4. Blender UID/GID `65534`, zero effective/permitted/ambient capabilities and
   `no-new-privileges`;
5. `--factory-startup --background --disable-autoexec --python-exit-code` with the bundled script;
6. rejection of scripts, drivers, external libraries, unpacked resources, non-finite/extreme
   transforms and bounded object/geometry/texture limits;
7. a second isolated Blender invocation that reopens the `.blend` and must reproduce the same
   strict report;
8. `O_NOFOLLOW`, regular-file/link-count, size, magic, hash and unexpected-file checks before the
   artifact leaves the private directory.

The main worker retains only the existing `SYS_ADMIN` capability needed by the other parser
network namespaces and keeps the default AppArmor/seccomp profiles; Blender never runs there.
Only the secretless, networkless, read-only-root `blender-runner` relaxes the profiles required to
create nested namespaces. The untrusted Blender process itself sees neither the main worker
filesystem nor its network, parent `/proc`, `/app`, credentials or capabilities.

## Honest boundary

This produces a downloadable, verified `.blend` handoff for single models and multi-object scenes.
It does not remotely control a desktop Blender installation, install an add-on, accept arbitrary
Blender automation, or turn shared Sova instances into linked Blender datablocks. Local one-click
desktop opening and an optional audited client/add-on remain separate contracts.
