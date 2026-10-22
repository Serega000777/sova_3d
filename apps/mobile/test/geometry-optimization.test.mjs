import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 82 reaches the typed exact optimizer with real material inputs", () => {
  assert.match(project, /client\.optimizeModel\(active\.id/);
  assert.match(project, /material_id: printMaterialId \|\| null/);
  assert.match(project, /printer_profile_id: printProfileId \|\| null/);
  assert.match(project, /load: "structural"/);
  assert.match(project, /opening: "bottom"/);
  assert.match(project, /preview: true/);
  assert.match(project, /if \(job\.status !== "succeeded"\)/);
});

test("optimization remains a draft with measured mass and explicit keep or discard", () => {
  assert.match(project, /showLocalEditPreview\(job, \{/);
  assert.match(project, /kind: "optimization"/);
  assert.match(project, /report\.mass_before_g/);
  assert.match(project, /report\.density_g_cm3/);
  assert.match(project, /beforeMassG/);
  assert.match(project, /afterMassG/);
  assert.match(project, /client\.acceptVersion\(localEditPreview\.version\.id\)/);
  assert.match(project, /client\.discardVersion\(localEditPreview\.version\.id\)/);
  assert.match(project, /не FEA и не сертификат прочности/);
});
