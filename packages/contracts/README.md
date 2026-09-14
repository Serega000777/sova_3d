# @physical-ai/contracts

Shared contracts for every client (web, mobile, desktop):

- `operation-plan.schema.json` + `src/operation-plan.ts` — the only thing an AI
  planner may emit (generated from `services/api/app/geometry/operations.py`).
- `integrity-report.schema.json`, `print-analysis.schema.json` — worker reports.
- `openapi.json` + `src/api.d.ts` — the REST API and its generated types.
- `src/client.ts` — `PhysicalAiClient`, a fetch-based typed client with bearer
  auth, the error envelope, idempotency keys and `waitForJob()`.
- `examples/` — reference OperationPlans (organizer, pipe bracket).

Regenerate after changing the API:

```bash
cd services/api && uv run python -m app.cli openapi > ../../packages/contracts/openapi.json
pnpm --filter @physical-ai/contracts generate && pnpm build
```
