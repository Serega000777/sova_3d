import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");
const card = readFileSync(new URL("../src/components/OptimizeCard.tsx", import.meta.url), "utf8");

const optimizer = studio.slice(
  studio.indexOf("async function optimizeGeometry"),
  studio.indexOf("async function decideOptimizationDraft"),
);
const decision = studio.slice(
  studio.indexOf("async function decideOptimizationDraft"),
  studio.indexOf("/** The engineer's fix"),
);

test("reference 82 sends the selected exact-print context and requests a bottom-open structural draft", () => {
  assert.match(optimizer, /client\.optimizeModel\(sourceVersion\.id/);
  assert.match(optimizer, /material_id: printMaterialId \|\| null/);
  assert.match(optimizer, /printer_profile_id: printProfileId \|\| null/);
  assert.match(optimizer, /load: "structural"/);
  assert.match(optimizer, /opening: "bottom"/);
  assert.match(optimizer, /preview: true/);
  assert.match(optimizer, /diff\.before\?\.version_id !== sourceVersion\.id/);
  assert.match(optimizer, /diff\.after\.version_id !== version\.id/);
});

test("optimization drafts are guarded by version printer material context and a revision", () => {
  assert.match(studio, /const optimizationContext = \[activeVersionId \?\? "", printProfileId, printMaterialId\]\.join\("\|"\)/);
  assert.match(studio, /optimizationContextRef\.current = optimizationContext/);
  assert.match(studio, /optimizationRevision\.current \+= 1/);
  assert.match(studio, /setOptimizationDraft\(null\)/);
  assert.match(optimizer, /const revision = optimizationRevision\.current/);
  assert.match(optimizer, /const context = optimizationContext/);
  assert.match(optimizer, /optimizationRevision\.current === revision/);
  assert.match(optimizer, /optimizationContextRef\.current === context/);
  assert.match(optimizer, /discardVersion\(version\.id\)/);
});

test("keep and discard explicitly resolve only the returned optimization draft", () => {
  assert.match(decision, /if \(keep\) await client\.acceptVersion\(draft\.version\.id\)/);
  assert.match(decision, /else await client\.discardVersion\(draft\.version\.id\)/);
  assert.match(decision, /setOptimizationDraft\(null\)/);
  assert.match(card, /onDecide\(true\)/);
  assert.match(card, /onDecide\(false\)/);
  assert.match(card, /Keep/);
  assert.match(card, /Discard/);
});

test("imported meshes fail closed while draft evidence includes images dimensions volume and material mass", () => {
  assert.match(optimizer, /operationStackStatus !== "present"/);
  assert.match(card, /operationStackStatus === "absent"/);
  assert.match(card, /imported mesh without operation history cannot use this exact hollowing tool/i);
  assert.match(card, /disabled=\{disabled \|\| deciding \|\| !supported\}/);
  assert.match(card, /draft\.beforeUrls\.iso/);
  assert.match(card, /draft\.afterUrls\.iso/);
  assert.match(card, /draft\.diff\.before\?\.size_mm/);
  assert.match(card, /draft\.diff\.after\.size_mm/);
  assert.match(card, /volume_delta_pct/);
  assert.match(card, /draft\.beforeMassG/);
  assert.match(card, /draft\.afterMassG/);
});
