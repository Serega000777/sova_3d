import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  MODEL_CHECK_GROUPS,
  modelCheckGroupStatus,
  parseOrdinaryModelCheck,
  verifiedModelCheckJob,
  verifiedPersistedModelCheck,
} from "../src/lib/model-check.ts";

const panel = readFileSync(new URL("../src/components/IntegrityCheckPanel.tsx", import.meta.url), "utf8");
const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

const geometry = (format: string) => ({
  format,
  bbox_size_mm: [10, 20, 30],
  faces: 12,
  vertices: 8,
  watertight: true,
  volume_mm3: 6000,
  surface_area_mm2: 2200,
  material_count: 0,
  texture_count: 0,
  node_count: 1,
  mesh_count: 1,
  animation_count: 0,
  camera_count: 0,
  light_count: 0,
});

const report = (overrides: Record<string, unknown> = {}) => ({
  schema_version: 1,
  source_format: "stl",
  target_format: "glb",
  printable_gate: false,
  status: "pass",
  checks: [],
  summary: "verified",
  source: geometry("stl"),
  output: geometry("glb"),
  ...overrides,
});

const job = (overrides: Record<string, unknown> = {}) => ({
  type: "export",
  status: "succeeded",
  project_version_id: "version-51",
  result: { format: "glb", printable_gate: false, report: report() },
  error: null,
  ...overrides,
}) as never;

test("reference 51 web check uses the exact non-mutating ordinary GLB pipeline", () => {
  assert.match(panel, /client\.exportModel\(versionId, \{[\s\S]*format: "glb",[\s\S]*printable: false,[\s\S]*game: null/);
  assert.match(panel, /verifiedModelCheckJob\(job, versionId\)/);
  assert.match(panel, /verifiedPersistedModelCheck\(persisted, accepted\.job_id\)/);
  assert.match(panel, /revision\.current !== request/);
  assert.match(studio, /tool === "integrity"/);
});

test("ordinary report parser and terminal job binding fail closed", () => {
  assert.equal(parseOrdinaryModelCheck(report())?.targetFormat, "glb");
  assert.equal(parseOrdinaryModelCheck(report({ target_format: "obj", output: geometry("obj") })), null);
  assert.equal(verifiedModelCheckJob(job(), "version-51")?.status, "pass");
  assert.equal(verifiedModelCheckJob(job(), "other-version"), null);
  assert.equal(verifiedModelCheckJob(job({ type: "game_export" }), "version-51"), null);
  assert.equal(verifiedModelCheckJob(job({ result: { format: "glb", printable_gate: true, report: report({ printable_gate: true }) } }), "version-51"), null);
  assert.equal(
    verifiedModelCheckJob(job({ status: "failed", result: null, error: { details: { report: report({ status: "fail" }) } } }), "version-51")?.status,
    "fail",
  );
});

test("persisted report must match the just-completed job", () => {
  const record = { job_id: "job-current", checked_at: "2026-11-05T00:00:00Z", report: report() } as never;
  assert.equal(verifiedPersistedModelCheck(record, "job-current")?.status, "pass");
  assert.equal(verifiedPersistedModelCheck(record, "job-older"), null);
});

test("appearance without canonical evidence stays unknown instead of green", () => {
  const parsed = parseOrdinaryModelCheck(report());
  assert.ok(parsed);
  assert.equal(modelCheckGroupStatus(parsed, MODEL_CHECK_GROUPS.appearance), "unknown");
  assert.match(panel, /groups\.appearance === "unknown"/);
  assert.match(panel, /Формат источника не содержит проверяемых данных/);
  assert.match(panel, /Готово с замечаниями/);
});

test("web presentation restores exact-version reports, groups facts, and downloads the authenticated PDF", () => {
  assert.match(panel, /client\.getLatestIntegrityReport\(versionId\)/);
  assert.match(panel, /reason instanceof ApiError\) \|\| reason\.status !== 404/);
  assert.match(panel, /MODEL_CHECK_GROUPS\.geometry/);
  assert.match(panel, /MODEL_CHECK_GROUPS\.scene/);
  assert.match(panel, /MODEL_CHECK_GROUPS\.appearance/);
  assert.match(panel, /MODEL_CHECK_GROUPS\.scale/);
  assert.match(panel, /client\.downloadIntegrityReport\(versionId\)/);
  assert.match(panel, /URL\.revokeObjectURL/);
  assert.match(panel, /не расчёт прочности, цифровая подпись или нормативная сертификация/);
});
