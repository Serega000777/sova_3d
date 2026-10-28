import assert from "node:assert/strict";
import { test } from "node:test";

import type { HouseTextProposal } from "../src/client.ts";
// client.ts uses parameter properties, which Node's strip-only TypeScript cannot load.
import { PhysicalAiClient } from "../dist/client.js";
import {
  houseTextApplyBody,
  houseTextFootprint,
  houseTextProposalIsExact,
  houseTextRefusal,
  houseTextRows,
} from "../src/house-text.ts";

const request = {
  length_mm: 12_000,
  width_mm: 8_000,
  floor_height_mm: 3_000,
  floors: 2,
  shape: "rectangle" as const,
};

const proposal: HouseTextProposal = {
  workspace_id: "ws-1",
  project_id: null,
  language: "ru",
  request,
  diff: [
    { field: "length_mm", label_ru: "Длина", label_en: "Length", before: null, after: 12_000, unit: "mm", source: "12 × 8 м" },
    { field: "width_mm", label_ru: "Ширина", label_en: "Width", before: null, after: 8_000, unit: "mm", source: "12 × 8 м" },
    { field: "floor_height_mm", label_ru: "Высота этажа", label_en: "Floor height", before: null, after: 3_000, unit: "mm", source: "высота этажа 3 м" },
    { field: "floors", label_ru: "Этажей", label_en: "Floors", before: null, after: 2, unit: "count", source: "двухэтажный" },
    { field: "shape", label_ru: "Форма", label_en: "Shape", before: null, after: "rectangle", unit: "enum", source: null },
  ],
  total_height_mm: 6_000,
  footprint_area_m2: 96,
  summary_ru: "Прямоугольный дом",
  summary_en: "Rectangular house",
  job_created: false,
  ai_used: false,
};

test("house text rows show canonical mm values with their source fragments", () => {
  const rows = houseTextRows(proposal, "en");
  assert.deepEqual(rows.map((row) => row.label), ["Length", "Width", "Floor height", "Floors", "Shape"]);
  assert.equal(rows[0]?.value, "12,000 mm");
  assert.equal(rows[2]?.source, "высота этажа 3 м");
  assert.equal(rows[3]?.value, "2");
  assert.equal(houseTextRows(proposal, "ru")[4]?.value, "Прямоугольник");
  const shaped = structuredClone(proposal);
  shaped.diff[4]!.after = "l_shape";
  assert.equal(houseTextRows(shaped, "en")[4]?.value, "L-shaped");
});

test("apply body echoes the exact proposed request and original prompt only", () => {
  const body = houseTextApplyBody(proposal, "Создай дом");
  assert.deepEqual(body, { workspace_id: "ws-1", project_id: null, prompt: "Создай дом", request });
  assert.notEqual(body.request, proposal.request);
});

test("a confirmable proposal is complete, target-bound, and internally consistent", () => {
  assert.equal(houseTextProposalIsExact(proposal, { workspaceId: "ws-1" }), true);

  for (const mutate of [
    (value: HouseTextProposal) => { value.workspace_id = "ws-2"; },
    (value: HouseTextProposal) => { value.project_id = "project-2"; },
    (value: HouseTextProposal) => { value.total_height_mm = 5_999; },
    (value: HouseTextProposal) => { value.footprint_area_m2 = 95; },
    (value: HouseTextProposal) => { value.diff[0]!.after = 11_000; },
    (value: HouseTextProposal) => { value.diff.pop(); },
    (value: HouseTextProposal) => { value.diff[1]!.field = "length_mm"; },
  ]) {
    const malformed = structuredClone(proposal);
    mutate(malformed);
    assert.equal(houseTextProposalIsExact(malformed, { workspaceId: "ws-1" }), false);
  }
});

test("house proposal footprint matches the canonical rectangle, L and T massing outlines", () => {
  assert.deepEqual(houseTextFootprint(request), [
    [0, 0], [12_000, 0], [12_000, 8_000], [0, 8_000],
  ]);
  assert.deepEqual(houseTextFootprint({ ...request, shape: "l_shape" }), [
    [0, 0], [12_000, 0], [12_000, 4_000], [6_000, 4_000], [6_000, 8_000], [0, 8_000],
  ]);
  assert.deepEqual(houseTextFootprint({ ...request, shape: "t_shape" }), [
    [4_000, 0], [8_000, 0], [8_000, 16_000 / 3], [12_000, 16_000 / 3],
    [12_000, 8_000], [0, 8_000], [0, 16_000 / 3], [4_000, 16_000 / 3],
  ]);
});

test("house proposal footprint fails closed for malformed dimensions or shapes", () => {
  assert.equal(houseTextFootprint({ ...request, length_mm: Number.NaN }), null);
  assert.equal(houseTextFootprint({ ...request, width_mm: 51_000 }), null);
  assert.equal(houseTextFootprint({ ...request, shape: "hexagon" as "rectangle" }), null);
});

test("client calls the read-only proposal endpoint and the idempotent apply endpoint", async () => {
  const calls: { url: string; init: RequestInit }[] = [];
  const client = new PhysicalAiClient({
    baseUrl: "http://api.test/",
    token: "t",
    fetch: (async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as typeof fetch,
  });
  await client.proposeHouseFromText({ workspace_id: "ws-1", prompt: "Создай дом" });
  await client.applyHouseFromText(houseTextApplyBody(proposal, "Создай дом"), "key-1");
  assert.equal(calls[0]?.url, "http://api.test/api/v1/house-boxes/text-proposal");
  assert.equal(calls[0]?.init.method, "POST");
  assert.equal((calls[0]?.init.headers as Record<string, string>)["Idempotency-Key"], undefined);
  assert.equal(calls[1]?.url, "http://api.test/api/v1/house-boxes/text-apply");
  assert.equal((calls[1]?.init.headers as Record<string, string>)["Idempotency-Key"], "key-1");
  assert.deepEqual(JSON.parse(String(calls[1]?.init.body)).request, request);
});

test("refusal reasons map to clear RU copy and unknown reasons keep the server text", () => {
  assert.equal(
    houseTextRefusal({ reason: "ambiguous_height", fragment: "высота 6 м" }, "x", "ru"),
    "Неясно, какая это высота. Напишите «высота этажа 3 м». («высота 6 м»)",
  );
  assert.match(houseTextRefusal({ reason: "missing_unit" }, "x", "ru"), /мм, см или м/);
  assert.equal(houseTextRefusal({ reason: "something_new" }, "server text", "ru"), "server text");
  assert.equal(houseTextRefusal(null, "server text", "en"), "server text");
});
