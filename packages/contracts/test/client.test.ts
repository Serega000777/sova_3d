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
