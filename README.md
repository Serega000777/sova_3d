# Physical AI 3D Platform

Describe an object in words or walk around it with a camera, and get a model you can edit
by the millimetre, check for printability and export — without knowing CAD.

The rule the whole system is built on: **the model never writes geometry.** An LLM emits a
typed, validated `OperationPlan`; a deterministic C++/OpenCASCADE kernel executes it. Every
accepted change is a new immutable version with its own lineage, so nothing is ever
overwritten and every model can explain where it came from.

Three more things a model can do once it exists, on every client:

- **Outline an area and say what belongs there** — draw on the surface with a mouse, a
  finger or a pencil, type "a 6 mm hole here" or "карман глубиной 3 мм", and the planner is
  held to that volume.
- **Paint it** — sweep a brush or fill a loop; colour is a layer, never a change of shape,
  it survives later edits, and it exports to GLB/PLY/OBJ.
- **Bring any model in, take any format out** — a finished Blender OBJ, a scan, a STEP file:
  import keeps the original, and `/convert` writes another format with an integrity report.

Engineering source: [`docs/`](docs/) (engineering pack 00–07,
[`AI_ENGINEERING_CONSTITUTION.md`](docs/AI_ENGINEERING_CONSTITUTION.md),
[`codex_tasks.json`](docs/codex_tasks.json)) and [`docs/v2/`](docs/v2/) (Source of Truth,
Feature Registry). Every product PR references `F-xxx` and `T-xxx`. Start with
[`docs/CODEX_START_HERE.md`](docs/CODEX_START_HERE.md).

## Run it

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml --env-file .env up -d --build --wait
docker compose -f infra/docker-compose.yml exec api uv run --no-sync python -m app.cli create-user --email you@example.com
pnpm install && pnpm --filter @physical-ai/web dev        # http://localhost:3100
```

Then sign in with the printed token and workspace id. Or watch the whole path run itself:

```bash
python demos/organizer_from_text.py     # a sentence -> an editable, printable model
python demos/scan_to_model.py           # frames -> a reconstruction you accept or retry
python demos/export_validated.py        # a model -> validated STL/3MF/GLB on disk
```

## Clients

| | | |
| --- | --- | --- |
| [`apps/web`](apps/web) | Next.js 16 + React Three Fiber | the workspace: prompt, viewport, outline + paint, numeric inspector, print check, exports, `/convert` |
| [`apps/mobile`](apps/mobile) | Expo SDK 57 / RN 0.86 | iOS + Android incl. iPad and Apple Pencil; **runs in Expo Go** ([why](apps/mobile/README.md)) |
| [`apps/desktop`](apps/desktop) | Tauri 2 | Windows and macOS window around the workspace |

## Services

| | | |
| --- | --- | --- |
| [`services/api`](services/api) | Python 3.13 / FastAPI | projects, immutable versions, AI commands, manual edits, scans, imports/conversion, painting, printing, exports, jobs |
| [`services/worker`](services/worker) | Python 3.13 | untrusted-file parsing, repair, printability, reconstruction, painting — everything in a sandbox |
| [`services/geometry`](services/geometry) | C++20 / OCCT 7.8 | the kernel: executes plans, imports STEP/IGES, writes B-Rep + mesh |

## Packages

- [`packages/contracts`](packages/contracts) — OpenAPI, generated TS types, operation and
  report schemas, the typed client all three clients share, and the outline rules that turn
  a drawn path into a region (tested on Node's own runner).

## Operating it

- [`infra/observability`](infra/observability) — one trace id from a click to the kernel,
  structured logs, Prometheus metrics and a Grafana dashboard.
- `docker compose -f infra/docker-compose.yml -f infra/docker-compose.ci.yml run --rm api-tests`
  runs the API suite inside the worker image, against the real kernel.
