import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { previewMatchesSource } from "../src/local-edit-preview.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 82 reaches the typed exact optimizer with real material inputs", () => {
  assert.match(project, /client\.optimizeModel\(sourceVersionId/);
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

test("optimization preview is bound to the exact immutable source", () => {
  const sourceVersionId = "source";
  const version = {
    id: "draft",
    parent_version_id: sourceVersionId,
    state: "draft",
  };
  const comparison = {
    before: { version_id: sourceVersionId },
    after: { version_id: version.id },
    awaiting_decision: true,
  };

  assert.equal(previewMatchesSource(version, comparison, sourceVersionId), true);
  assert.equal(previewMatchesSource({ ...version, parent_version_id: "other" }, comparison, sourceVersionId), false);
  assert.equal(previewMatchesSource({ ...version, state: "finalized" }, comparison, sourceVersionId), false);
  assert.equal(previewMatchesSource(version, { ...comparison, before: { version_id: "other" } }, sourceVersionId), false);
  assert.equal(previewMatchesSource(version, { ...comparison, after: { version_id: "other" } }, sourceVersionId), false);
  assert.equal(previewMatchesSource(version, { ...comparison, awaiting_decision: false }, sourceVersionId), false);
  assert.match(project, /sourceVersionId = active\.id/);
  assert.match(project, /previewMatchesSource\(version, diff, context\.sourceVersionId\)/);
});
