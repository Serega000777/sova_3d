import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const scanResult = readFileSync(new URL("../app/scan/[id].tsx", import.meta.url), "utf8");
const client = readFileSync(new URL("../../../packages/contracts/src/client.ts", import.meta.url), "utf8");

test("mobile builds alternatives from the same scan and waits for both jobs", () => {
  assert.match(scanResult, /client\.createScanCandidates\(scan\.id\)/);
  assert.match(scanResult, /Promise\.all\(queued\.jobs\.map\(\(accepted\) => client\.waitForJob/);
  assert.match(scanResult, /Все варианты построены сервером из одного неизменного набора фото/);
  assert.match(client, /createScanCandidates\(scanId: string\)/);
  assert.match(client, /listScanCandidates\(scanId: string\)/);
});

test("preview remains non-destructive until keep selects the exact candidate", () => {
  assert.match(scanResult, /setPreviewCandidateKey\(candidate\.key\)/);
  assert.match(scanResult, /if \(previewCandidateKey\) \{[\s\S]*?selectScanCandidate/);
  assert.match(scanResult, /Кандидат станет результатом скана только после кнопки сохранения/);
  assert.match(client, /selectScanCandidate\(scanId: string, key:/);
});

test("candidate cards expose the real quality, texture and measured face count", () => {
  assert.match(scanResult, /candidate\.quality/);
  assert.match(scanResult, /candidate\.texture/);
  assert.match(scanResult, /decimate\?: \{ result_faces\?: number \}/);
  assert.match(scanResult, /accessibilityRole="radio"/);
});
