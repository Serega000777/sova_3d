# Physical AI 3D Platform — starter monorepo

Engineering source: [`docs/`](docs/) (engineering pack 00–07, `AI_ENGINEERING_CONSTITUTION.md`,
`codex_tasks.json`) and [`docs/v2/`](docs/v2/) (v2 Source of Truth, Feature Registry, v1 core docs).
Every product PR must reference `F-xxx` and `T-xxx`. Start with [`docs/CODEX_START_HERE.md`](docs/CODEX_START_HERE.md).

## Apps
- `apps/web` — Next.js
- `apps/mobile` — Expo / React Native + native scan modules
- `apps/desktop` — Tauri + React

## Services
- `services/api` — FastAPI orchestration/API
- `services/worker` — general async workers
- `services/ai-worker` — AI/GPU adapters
- `services/geometry` — C++/OpenCASCADE deterministic CAD

## Packages
- `packages/contracts` — OpenAPI/generated types/operation schemas
- `packages/ui` — shared design primitives
- `packages/three-viewer` — shared 3D viewport logic

Start local infra: `docker compose -f infra/docker-compose.yml up -d`.
