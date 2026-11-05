import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  parsePrintDiagnosis,
  photoDiagnosisEvidence,
  verifiedPhotoDiagnosisJob,
} from "../src/lib/print-diagnosis.ts";

const panel = readFileSync(new URL("../src/components/PrintDoctorPanel.tsx", import.meta.url), "utf8");
const printers = readFileSync(new URL("../src/app/printers/page.tsx", import.meta.url), "utf8");

const diagnosis = (overrides: Record<string, unknown> = {}) => ({
  material_id: "pla",
  outcome: "partial",
  findings: [{ symptom: "stringing", causes: ["temperature"], changes: [{ setting: "retraction_mm", before: 0.8, after: 1 }], advice: "Run a small test." }],
  tuning: { retraction_mm: 0.8 },
  applied: false,
  reports: 1,
  ...overrides,
});

test("reference 57 web Print Doctor has photo analysis and a provider-free manual fallback", () => {
  assert.match(panel, /client\.uploadFile\(workspaceId, photo, photo\.name, photo\.type\)/);
  assert.match(panel, /client\.reportPrintPhotos\(profile\.id/);
  assert.match(panel, /client\.reportPrint\(profile\.id/);
  assert.match(panel, /photo_diagnosis_not_enabled/);
  assert.match(panel, /setPhotos\(\[\]\)/);
  assert.match(panel, /Убрать фото/);
  assert.match(panel, /Ручной fallback работает без AI-провайдера/);
  assert.match(printers, /<PrintDoctorPanel/);
});

test("diagnosis parser binds material and apply state and rejects malformed changes", () => {
  assert.equal(parsePrintDiagnosis(diagnosis(), "pla", false)?.findings[0]?.symptom, "stringing");
  assert.equal(parsePrintDiagnosis(diagnosis(), "petg", false), null);
  assert.equal(parsePrintDiagnosis(diagnosis(), "pla", true), null);
  assert.equal(parsePrintDiagnosis(diagnosis({ findings: [{ symptom: "unknown", causes: [], changes: [], advice: "" }] }), "pla", false), null);
  assert.equal(parsePrintDiagnosis(diagnosis({ findings: [{ symptom: "stringing", causes: ["heat"], changes: [{ setting: "flow_pct", before: 100, after: Number.NaN }], advice: "test" }] }), "pla", false), null);
});

test("photo jobs are accepted only from the current workspace and expected job type", () => {
  const job = { type: "diagnose_print_photo", workspace_id: "workspace-1", status: "succeeded", result: diagnosis() } as never;
  assert.equal(verifiedPhotoDiagnosisJob(job, "workspace-1", "pla")?.material_id, "pla");
  assert.equal(verifiedPhotoDiagnosisJob(job, "workspace-2", "pla"), null);
  assert.equal(verifiedPhotoDiagnosisJob({ ...job, type: "export" }, "workspace-1", "pla"), null);
  assert.equal(verifiedPhotoDiagnosisJob({ ...job, status: "failed" }, "workspace-1", "pla"), null);
});

test("photo evidence is bounded to recognized symptoms and confident finite observations", () => {
  const evidence = photoDiagnosisEvidence({ photo: { seen: [
    { symptom: "stringing", evidence: "fine threads", confidence: 0.8 },
    { symptom: "warping", evidence: "weak", confidence: 0.2 },
    { symptom: "invented", evidence: "no", confidence: 0.9 },
  ] } });
  assert.deepEqual(evidence, [{ symptom: "stringing", evidence: "fine threads", confidence: 0.8 }]);
});

test("recommendations require a second explicit apply and state their future-only boundary", () => {
  assert.match(panel, /apply: false/);
  assert.match(panel, /symptoms: diagnosis\.findings\.map/);
  assert.match(panel, /apply: true/);
  assert.match(panel, /parsePrintDiagnosis\(response, diagnosis\.material_id, true\)/);
  assert.match(panel, /только на будущий слайсинг/);
  assert.match(panel, /Модель и уже созданный G-code не меняются/);
  assert.doesNotMatch(panel, /bounding.?box|дефект найден в координатах/i);
});

test("periodic reference audit proves existing web printer-profile and calibration parity", () => {
  assert.match(printers, /client\.listPrinterProfiles\(session\.workspaceId\)/);
  assert.match(printers, /client\.listPrinterModels\(\)/);
  assert.match(printers, /client\.createPrinterProfile\(buildPrinterProfileCreatePayload/);
  assert.match(printers, /client\.updatePrinterProfile\(profile\.id, \{ is_default: true \}\)/);
  assert.match(printers, /client\.startCalibrationPrint\(profile\.id\)/);
  assert.match(printers, /client\.waitForJob\(started\.job\.job_id\)/);
  assert.match(printers, /router\.push\(`\/projects\/\$\{started\.project_id\}`\)/);
  assert.match(printers, /client\.recordCalibration\(profile\.id, readings\)/);
  assert.match(printers, /hole_3_mm[\s\S]*hole_5_mm[\s\S]*hole_8_mm[\s\S]*peg_5_mm[\s\S]*peg_8_mm[\s\S]*length_60_mm[\s\S]*wall_mm/);
});
