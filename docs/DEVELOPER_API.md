# Developer API (F-066)

Sova exposes the same versioned REST API used by its web, mobile and desktop clients.
The canonical machine-readable contract is [`packages/contracts/openapi.json`](../packages/contracts/openapi.json),
and the generated TypeScript client is `@physical-ai/contracts`.

## Create an integration key

Open **Settings → Developer API** while signed in. Give the key a name and a bounded lifetime
(30, 90 or 365 days). The plaintext `pai_…` value is shown exactly once. The server stores only
its SHA-256 hash. Revoke the key from the same screen when the integration is retired.

Never put a key in browser code, source control, logs or a mobile bundle. Keep it in the
integration's secret store and send it only as a bearer token over HTTPS:

```bash
curl "$SOVA_API_BASE/api/v1/projects?workspace_id=$SOVA_WORKSPACE_ID" \
  -H "Authorization: Bearer $SOVA_API_TOKEN"
```

## Typed TypeScript client

```ts
import { PhysicalAiClient } from "@physical-ai/contracts";

const client = new PhysicalAiClient({
  baseUrl: process.env.SOVA_API_BASE!,
  token: process.env.SOVA_API_TOKEN!,
});

const projects = await client.listProjects(process.env.SOVA_WORKSPACE_ID!);
```

Generation, import/conversion, print checks and exports are asynchronous: their endpoints return a
`job_id`; call `waitForJob(job_id)` or poll `GET /api/v1/jobs/{job_id}`. Mutating endpoints that
accept `Idempotency-Key` should receive a stable key for safe retries. Workspace and project
authorization is identical for developer keys and interactive sessions.

Developer keys do not bypass plan entitlements, workspace roles, usage limits or validation. A
revoked or expired key receives `401`; an inaccessible workspace resource remains `404`.
