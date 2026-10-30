# Sova 3D MCP server

Sova MCP is a narrow local facade over the provider-neutral 3D generation API. It does not
open the database, object storage, filesystem, or Blender to an agent. Existing API bearer
authentication and workspace authorization remain the security boundary.

## Configuration

Create a token for a dedicated least-privilege Sova user, allowlist the exact project UUIDs, and
provide all three values only to the MCP process:

```bash
export SOVA_MCP_API_URL=http://127.0.0.1:8000/api/v1
export SOVA_MCP_TOKEN=<dedicated-user-api-token>
export SOVA_MCP_PROJECT_IDS=<project-uuid>[,<project-uuid>...]
uv run --directory services/api sova3d-mcp
```

`SOVA_MCP_API_URL` defaults to the loopback URL above. Plain HTTP is refused for non-loopback
hosts; remote APIs require HTTPS. Credentials, query parameters, and fragments are refused in
the URL. Sova API tokens are user-scoped, not workspace-scoped; every project/job MCP tool also
checks `SOVA_MCP_PROJECT_IDS`, but the dedicated user must still have only the intended Sova
memberships. The token and allowlist are never tool arguments and must not be placed in an agent
prompt or MCP client configuration visible to the model.

## Tools

- `sova3d.providers` — enabled provider-neutral capabilities.
- `sova3d.estimate` — cost and latency estimate plus a request-bound receipt valid for 15 minutes.
- `sova3d.generate` — durable generation with the matching one-use receipt, caller confirmation,
  and an idempotency key.
- `sova3d.get_job` — normalized progress, artifacts, quality report, and terminal error; requires
  the allowlisted project UUID and verifies it against the returned job.
- `sova3d.benchmark` — workspace-scoped provider/model quality, latency, cost, and outcomes.

The intended flow is `estimate → caller confirmation → generate → get_job`. The receipt binds the
exact project and normalized request and is consumed atomically before the first generation-start
network attempt. If that attempt has an ambiguous transport outcome, obtain a new estimate and
use the same idempotency key to resolve the API-side job safely. A receipt does not prove a human
approval; clients that require one must collect it before setting `confirmed_estimate=true`.
Generation retains the API's fail-closed budget, privacy, retention, training-consent, and
provider-routing rules.

## Deliberate exclusions

This first surface has no upload, delete, cancel, raw signed-URL, arbitrary HTTP, direct storage,
or arbitrary Blender/Python execution tool. Those operations require separate bounded contracts
and security review. MCP responses are streamed and aborted above 1 MiB, redirects are not
followed, outputs are schema-validated, and Sova error-envelope messages redact the configured
bearer token.
