import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const clientSource = await readFile(new URL("../src/client.ts", import.meta.url), "utf8");
const standaloneClientSource = clientSource.replace(
  'import { type LiveEvent, LiveRoom, liveUrl } from "./live.js";',
  `type LiveEvent = unknown;
   class LiveRoom { constructor(..._args: unknown[]) {} }
   const liveUrl = (..._args: unknown[]) => "";`,
);
const compiledClient = ts.transpileModule(standaloneClientSource, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { ApiError, PhysicalAiClient } = await import(
  `data:text/javascript;base64,${Buffer.from(compiledClient).toString("base64")}`
);

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

test("non-JSON HTTP errors become ApiError instead of leaking a JSON parse failure", async () => {
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    fetch: async () =>
      new Response("<html>bad gateway</html>", {
        status: 502,
        statusText: "Bad Gateway",
        headers: { "content-type": "text/html" },
      }),
  });

  await assert.rejects(client.getJob("job-1"), (reason: unknown) => {
    assert.ok(reason instanceof ApiError);
    assert.equal(reason.status, 502);
    assert.equal(reason.code, "http_error");
    assert.equal(reason.message, "Bad Gateway");
    return true;
  });
});

test("401 responses invoke the unauthorized hook and still reject with ApiError", async () => {
  let unauthorizedCalls = 0;
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    token: "expired-token",
    onUnauthorized: () => {
      unauthorizedCalls += 1;
    },
    fetch: async () =>
      jsonResponse(
        { error: { code: "unauthorized", message: "Session expired", details: null, trace_id: "trace-1" } },
        { status: 401, statusText: "Unauthorized" },
      ),
  });

  await assert.rejects(client.me(), (reason: unknown) => {
    assert.ok(reason instanceof ApiError);
    assert.equal(reason.status, 401);
    assert.equal(reason.code, "unauthorized");
    return true;
  });
  assert.equal(unauthorizedCalls, 1);
});

test("team workspace creation posts the normalized typed body", async () => {
  let request: { url: string; init: RequestInit } | null = null;
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    token: "team-token",
    fetch: async (url: string, init: RequestInit) => {
      request = { url, init };
      return jsonResponse(
        { id: "workspace-2", name: "Studio North", kind: "team", role: "owner" },
        { status: 201 },
      );
    },
  });

  const workspace = await client.createTeamWorkspace({ name: "Studio North" });
  assert.equal(workspace.role, "owner");
  assert.equal(request!.url, "https://api.example.test/api/v1/workspaces");
  assert.equal(request!.init.method, "POST");
  assert.equal(new Headers(request!.init.headers).get("Authorization"), "Bearer team-token");
  assert.deepEqual(JSON.parse(String(request!.init.body)), { name: "Studio North" });
});

test("team workspace tasks use the nested typed routes and revision guard", async () => {
  const requests: { url: string; init: RequestInit }[] = [];
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    token: "team-token",
    fetch: async (url: string, init: RequestInit) => {
      requests.push({ url, init });
      if (init.method === "GET") {
        return jsonResponse({ open_count: 1, total_count: 1, tasks: [] });
      }
      return jsonResponse({
        id: "task-1",
        workspace_id: "workspace-2",
        title: "Review model",
        completed: init.method === "PATCH",
        completed_at: init.method === "PATCH" ? "2026-11-02T00:00:00Z" : null,
        revision: init.method === "PATCH" ? 1 : 0,
        created_by: "user-1",
        created_at: "2026-11-02T00:00:00Z",
        updated_at: "2026-11-02T00:00:00Z",
      }, { status: init.method === "POST" ? 201 : 200 });
    },
  });

  const list = await client.listWorkspaceTasks("workspace-2");
  assert.equal(list.open_count, 1);
  await client.createWorkspaceTask("workspace-2", { title: "Review model" });
  await client.updateWorkspaceTask("workspace-2", "task-1", {
    expected_revision: 0,
    completed: true,
  });
  assert.deepEqual(requests.map((item) => [item.init.method, item.url]), [
    ["GET", "https://api.example.test/api/v1/workspaces/workspace-2/tasks"],
    ["POST", "https://api.example.test/api/v1/workspaces/workspace-2/tasks"],
    ["PATCH", "https://api.example.test/api/v1/workspaces/workspace-2/tasks/task-1"],
  ]);
  assert.deepEqual(JSON.parse(String(requests[2]!.init.body)), {
    expected_revision: 0,
    completed: true,
  });
});

test("quad remesh posts the bounded target_faces and an idempotency key", async () => {
  let request: { url: string; init: RequestInit } | null = null;
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    token: "studio-token",
    fetch: async (url: string, init: RequestInit) => {
      request = { url, init };
      return jsonResponse({ job_id: "job-9", status: "queued", type: "quad_remesh" }, { status: 202 });
    },
  });

  const accepted = await client.createQuadRemesh(
    "version-1",
    { target_faces: 8000 },
    "quad-remesh-1",
  );
  assert.equal(accepted.job_id, "job-9");
  assert.equal(request!.url, "https://api.example.test/api/v1/models/version-1/quad-remeshes");
  assert.equal(request!.init.method, "POST");
  assert.equal(new Headers(request!.init.headers).get("Idempotency-Key"), "quad-remesh-1");
  assert.deepEqual(JSON.parse(String(request!.init.body)), { target_faces: 8000 });
});

test("paint-layer reorder posts the complete bottom-to-top order", async () => {
  let request: { url: string; init: RequestInit } | null = null;
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    token: "paint-token",
    fetch: async (url: string, init: RequestInit) => {
      request = { url, init };
      return jsonResponse({ job_id: "job-paint", status: "queued", type: "paint_model" }, { status: 202 });
    },
  });

  const accepted = await client.reorderPaintLayers("version-1", ["Accent", "Base"]);
  assert.equal(accepted.job_id, "job-paint");
  assert.equal(
    request!.url,
    "https://api.example.test/api/v1/models/version-1/paint/reorder-layers",
  );
  assert.equal(request!.init.method, "POST");
  assert.deepEqual(JSON.parse(String(request!.init.body)), {
    layer_order: ["Accent", "Base"],
  });
});

test("3D generation estimate posts the typed request and returns an honest null cost", async () => {
  let request: { url: string; init: RequestInit } | null = null;
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    token: "studio-token",
    fetch: async (url: string, init: RequestInit) => {
      request = { url, init };
      return jsonResponse({
        provider: "shap_e",
        model: "text300M",
        provider_version: "50131012",
        credits: "60",
        cost_usd: null,
        latency_seconds_min: 60,
        latency_seconds_max: 4200,
        target_format: "glb",
        assumptions: ["CPU-only self-hosted Shap-E; infrastructure cost is not yet converted to USD"],
      });
    },
  });

  const estimate = await client.estimateThreeDGeneration("project-1", {
    mode: "text",
    purpose: "standard",
    prompt: "a small ceramic owl",
    size_mm: 60,
    quality: "fast",
    target_format: "glb",
    pbr: false,
    rig: "none",
  });

  assert.equal(estimate.cost_usd, null);
  assert.equal(estimate.latency_seconds_min, 60);
  assert.equal(estimate.latency_seconds_max, 4200);
  assert.equal(request!.url, "https://api.example.test/api/v1/projects/project-1/3d-generations/estimate");
  assert.equal(request!.init.method, "POST");
  assert.deepEqual(JSON.parse(String(request!.init.body)), {
    mode: "text",
    purpose: "standard",
    prompt: "a small ceramic owl",
    size_mm: 60,
    quality: "fast",
    target_format: "glb",
    pbr: false,
    rig: "none",
  });
});

test("model comments use version-scoped create and revision-guarded update routes", async () => {
  const requests: { url: string; init: RequestInit }[] = [];
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    fetch: async (url: string, init: RequestInit) => {
      requests.push({ url, init });
      return jsonResponse({
        id: "comment-1",
        version_id: "version-1",
        comment: "Check edge",
        point_mm: [1, 2, 3],
        status: requests.length === 1 ? "open" : "resolved",
        revision: requests.length,
        created_by: "user-1",
        author_name: "Alex",
        created_at: "2026-10-27T00:00:00Z",
        updated_at: "2026-10-27T00:00:00Z",
        updated_by: "user-1",
        photo_asset_ids: requests.length === 3 ? ["asset-1"] : [],
      }, { status: requests.length === 1 ? 201 : 200 });
    },
  });

  await client.createModelComment("version-1", "Check edge", [1, 2, 3]);
  await client.updateModelComment("comment-1", "Check edge", "resolved", 1);
  await client.addModelCommentPhoto("comment-1", "asset-1", 2);
  await client.removeModelCommentPhoto("comment-1", "asset-1", 3);
  await client.createModelCommentReply("comment-1", "I will check", ["user-2"]);
  assert.equal(requests[0].url, "https://api.example.test/api/v1/versions/version-1/model-comments");
  assert.equal(requests[0].init.method, "POST");
  assert.deepEqual(JSON.parse(String(requests[0].init.body)), {
    comment: "Check edge",
    point_mm: [1, 2, 3],
  });
  assert.equal(requests[1].url, "https://api.example.test/api/v1/model-comments/comment-1");
  assert.equal(requests[1].init.method, "PATCH");
  assert.deepEqual(JSON.parse(String(requests[1].init.body)), {
    comment: "Check edge",
    status: "resolved",
    base_revision: 1,
  });
  assert.equal(requests[2].url, "https://api.example.test/api/v1/model-comments/comment-1/photos");
  assert.equal(requests[2].init.method, "POST");
  assert.deepEqual(JSON.parse(String(requests[2].init.body)), {
    asset_id: "asset-1",
    base_revision: 2,
  });
  assert.equal(
    requests[3].url,
    "https://api.example.test/api/v1/model-comments/comment-1/photos/asset-1?base_revision=3",
  );
  assert.equal(requests[4].url, "https://api.example.test/api/v1/model-comments/comment-1/replies");
  assert.equal(requests[4].init.method, "POST");
  assert.deepEqual(JSON.parse(String(requests[4].init.body)), {
    comment: "I will check",
    mentioned_user_ids: ["user-2"],
  });
  assert.equal(requests[3].init.method, "DELETE");
});

test("waitForJob retries network and 5xx failures with backoff until the job succeeds", async () => {
  let calls = 0;
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    fetch: async () => {
      calls += 1;
      if (calls === 1) return jsonResponse({ id: "job-1", status: "running" });
      if (calls === 2) throw new TypeError("temporary network failure");
      if (calls === 3) {
        return new Response("temporarily unavailable", { status: 503, statusText: "Service Unavailable" });
      }
      return jsonResponse({ id: "job-1", status: "succeeded", result: { version_id: "version-1" } });
    },
  });

  const progress: string[] = [];
  const job = await client.waitForJob("job-1", {
    intervalMs: 1,
    timeoutMs: 500,
    onProgress: (next) => progress.push(next.status),
  });

  assert.equal(job.status, "succeeded");
  assert.equal(calls, 4);
  assert.deepEqual(progress, ["running", "succeeded"]);
});

test("sliding lid posts the versioned mechanism route with an idempotency key", async () => {
  const calls: { url: string; init: RequestInit }[] = [];
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    fetch: async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return jsonResponse({ job_id: "job-1", status: "queued", type: "build_sliding_lid" }, { status: 202 });
    },
  });
  const accepted = await client.buildSlidingLid(
    "version-1",
    { width_mm: 100, depth_mm: 70, max_travel_mm: 55 },
    "slide-key",
  );
  assert.equal(accepted.type, "build_sliding_lid");
  assert.equal(calls.length, 1);
  assert.equal(calls[0]!.url, "https://api.example.test/api/v1/models/version-1/mechanisms/sliding-lid");
  assert.equal(calls[0]!.init.method, "POST");
  assert.equal(new Headers(calls[0]!.init.headers).get("Idempotency-Key"), "slide-key");
  assert.deepEqual(JSON.parse(String(calls[0]!.init.body)), { width_mm: 100, depth_mm: 70, max_travel_mm: 55 });
});

test("animation commands use separate read-only proposal and immutable apply routes", async () => {
  const calls: { url: string; init: RequestInit }[] = [];
  const clip = {
    schema_version: 1,
    kind: "rigid_joint_clip",
    joint_type: "revolute",
    node_id: "lid",
    duration_seconds: 2,
    direction: "reverse",
  };
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    fetch: async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return calls.length === 1
        ? jsonResponse({ clip, language: "en", job_created: false, ai_used: false })
        : jsonResponse({ version_id: "version-2", clip });
    },
  });

  const proposal = await client.proposeAnimationCommand("version-1", "close in 2 seconds");
  const applied = await client.applyAnimationCommand("version-1", "close in 2 seconds", proposal.clip);

  assert.equal(proposal.job_created, false);
  assert.equal(applied.version_id, "version-2");
  assert.equal(calls[0]!.url, "https://api.example.test/api/v1/models/version-1/animation-command-proposal");
  assert.equal(calls[0]!.init.method, "POST");
  assert.deepEqual(JSON.parse(String(calls[0]!.init.body)), { prompt: "close in 2 seconds" });
  assert.equal(calls[1]!.url, "https://api.example.test/api/v1/models/version-1/animation-command-apply");
  assert.equal(calls[1]!.init.method, "POST");
  assert.deepEqual(JSON.parse(String(calls[1]!.init.body)), {
    prompt: "close in 2 seconds",
    clip,
  });
});

test("turntable video posts the immutable version render route", async () => {
  let request: { url: string; init: RequestInit } | null = null;
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    fetch: async (url: string, init: RequestInit) => {
      request = { url, init };
      return jsonResponse(
        { job_id: "job-video", status: "queued", type: "render_turntable_video" },
        { status: 202 },
      );
    },
  });

  const accepted = await client.renderVersionTurntableVideo("version-1");

  assert.equal(accepted.type, "render_turntable_video");
  assert.equal(
    request!.url,
    "https://api.example.test/api/v1/versions/version-1/turntable-video",
  );
  assert.equal(request!.init.method, "POST");
  assert.equal(request!.init.body, undefined);
});

test("house document requests an authenticated PDF blob", async () => {
  let request: { url: string; init: RequestInit } | null = null;
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    token: "market-token",
    fetch: async (url: string, init: RequestInit) => {
      request = { url, init };
      return new Response(new Uint8Array([0x25, 0x50, 0x44, 0x46]), {
        headers: { "content-type": "application/pdf" },
      });
    },
  });

  const document = await client.downloadHouseDocument("listing-1");
  assert.equal(document.type, "application/pdf");
  assert.equal(document.size, 4);
  assert.equal(request!.url, "https://api.example.test/api/v1/listings/listing-1/documents/house.pdf");
  const headers = new Headers(request!.init.headers);
  assert.equal(headers.get("Authorization"), "Bearer market-token");
  assert.equal(headers.get("Accept"), "application/pdf");
});

test("integrity document requests the version-bound authenticated PDF", async () => {
  let request: { url: string; init: RequestInit } | null = null;
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    token: "model-token",
    fetch: async (url: string, init: RequestInit) => {
      request = { url, init };
      return new Response(new Uint8Array([0x25, 0x50, 0x44, 0x46]), {
        headers: { "content-type": "application/pdf" },
      });
    },
  });

  const document = await client.downloadIntegrityReport("version-2");
  assert.equal(document.type, "application/pdf");
  assert.equal(request!.url, "https://api.example.test/api/v1/models/version-2/integrity-report.pdf");
  const headers = new Headers(request!.init.headers);
  assert.equal(headers.get("Authorization"), "Bearer model-token");
  assert.equal(headers.get("Accept"), "application/pdf");
});

test("house schedule requests an authenticated XLSX blob", async () => {
  let request: { url: string; init: RequestInit } | null = null;
  const mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    token: "market-token",
    fetch: async (url: string, init: RequestInit) => {
      request = { url, init };
      return new Response(new Uint8Array([0x50, 0x4b, 0x03, 0x04]), {
        headers: { "content-type": mime },
      });
    },
  });

  const document = await client.downloadHouseSpreadsheet("listing-1");
  assert.equal(document.type, mime);
  assert.equal(document.size, 4);
  assert.equal(request!.url, "https://api.example.test/api/v1/listings/listing-1/documents/house.xlsx");
  const headers = new Headers(request!.init.headers);
  assert.equal(headers.get("Authorization"), "Bearer market-token");
  assert.equal(headers.get("Accept"), mime);
});

test("house drawing requests an authenticated DXF blob", async () => {
  let request: { url: string; init: RequestInit } | null = null;
  const mime = "application/dxf";
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    token: "market-token",
    fetch: async (url: string, init: RequestInit) => {
      request = { url, init };
      return new Response(new Uint8Array([0x30, 0x0d, 0x0a]), {
        headers: { "content-type": mime },
      });
    },
  });

  const document = await client.downloadHouseDrawing("listing-1");
  assert.equal(document.type, mime);
  assert.equal(document.size, 3);
  assert.equal(request!.url, "https://api.example.test/api/v1/listings/listing-1/documents/house.dxf");
  const headers = new Headers(request!.init.headers);
  assert.equal(headers.get("Authorization"), "Bearer market-token");
  assert.equal(headers.get("Accept"), mime);
});

test("verification link creation posts the expiry and returns the one-time token", async () => {
  let request: { url: string; init: RequestInit } | null = null;
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    token: "owner-token",
    fetch: async (url: string, init: RequestInit) => {
      request = { url, init };
      return new Response(
        JSON.stringify({ id: "link-1", token: "vrf_abc", expires_at: "2026-12-01T00:00:00Z" }),
        { headers: { "content-type": "application/json" } },
      );
    },
  });

  const created = await client.createVerificationLink("version-1", { expires_in_hours: 72 });
  assert.equal(created.token, "vrf_abc");
  assert.equal(
    request!.url,
    "https://api.example.test/api/v1/models/version-1/verification-links",
  );
  assert.equal(request!.init.method, "POST");
  assert.deepEqual(JSON.parse(request!.init.body as string), { expires_in_hours: 72 });
  const headers = new Headers(request!.init.headers);
  assert.equal(headers.get("Authorization"), "Bearer owner-token");
});

test("opening an integrity verification link needs no bearer token", async () => {
  let request: { url: string; init: RequestInit } | null = null;
  const report = {
    project_name: "Crate",
    version_id: "version-1",
    version_sequence_no: 1,
    job_id: "job-1",
    checked_at: "2026-11-02T00:00:00Z",
    report: { status: "pass" },
    link_expires_at: "2026-12-01T00:00:00Z",
  };
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    fetch: async (url: string, init: RequestInit) => {
      request = { url, init };
      return new Response(JSON.stringify(report), {
        headers: { "content-type": "application/json" },
      });
    },
  });

  const opened = await client.openIntegrityVerification("vrf_abc");
  assert.deepEqual(opened, report);
  assert.equal(request!.url, "https://api.example.test/api/v1/verify/vrf_abc");
  const headers = new Headers(request!.init.headers);
  assert.equal(headers.has("Authorization"), false);
});

test("buyer Sova package requests the authenticated order archive", async () => {
  let request: { url: string; init: RequestInit } | null = null;
  const mime = "application/vnd.sova.project+zip";
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    token: "market-token",
    fetch: async (url: string, init: RequestInit) => {
      request = { url, init };
      return new Response(new Uint8Array([0x50, 0x4b, 0x03, 0x04]), {
        headers: { "content-type": mime },
      });
    },
  });

  const projectPackage = await client.downloadOrderSovaPackage("order-1");
  assert.equal(projectPackage.type, mime);
  assert.equal(projectPackage.size, 4);
  assert.equal(
    request!.url,
    "https://api.example.test/api/v1/me/orders/order-1/project.sova",
  );
  const headers = new Headers(request!.init.headers);
  assert.equal(headers.get("Authorization"), "Bearer market-token");
  assert.equal(headers.get("Accept"), mime);
});

test("printer control posts the typed action to the selected profile", async () => {
  let request: { url: string; init: RequestInit } | null = null;
  const client = new PhysicalAiClient({
    baseUrl: "https://api.example.test",
    token: "printer-token",
    fetch: async (url: string, init: RequestInit) => {
      request = { url, init };
      return jsonResponse({ provider: "octoprint", state: "Pausing" });
    },
  });

  await client.controlPrinter("profile-1", "pause");
  assert.equal(
    request!.url,
    "https://api.example.test/api/v1/printer-profiles/profile-1/live/control",
  );
  assert.equal(request!.init.method, "POST");
  assert.deepEqual(JSON.parse(String(request!.init.body)), { action: "pause" });
  const headers = new Headers(request!.init.headers);
  assert.equal(headers.get("Authorization"), "Bearer printer-token");
});
