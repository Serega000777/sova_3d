import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildCadReconstructionProposal,
  buildFragmentRestorationProposal,
  fragmentRestorationPreviewTransform,
} from "../src/fragment-restoration.ts";

test("builds a version-bound exact mirror proposal without starting a job", () => {
  assert.deepEqual(buildFragmentRestorationProposal({
    sourceVersionId: "version-a",
    tolerance: "0,25",
    boundary: "x_max",
    reinforce: true,
    reinforcementPercent: "15",
  }), {
    sourceVersionId: "version-a",
    body: {
      tolerance_mm: 0.25,
      threads: true,
      restore_missing_half: "x_max",
      reinforce_thickness_percent: 15,
    },
  });
});
test("fails closed for invalid or incompatible restoration inputs", () => {
  const base = {
    sourceVersionId: "version-a",
    tolerance: "0.2",
    boundary: "x_min",
    reinforce: false,
    reinforcementPercent: "20",
  };
  assert.throws(() => buildFragmentRestorationProposal({ ...base, boundary: null }), /границу/);
  assert.throws(() => buildFragmentRestorationProposal({ ...base, tolerance: "0.01" }), /Допуск/);
  assert.throws(() => buildFragmentRestorationProposal({ ...base, reinforce: true, reinforcementPercent: "51" }), /50%/);
  assert.throws(() => buildFragmentRestorationProposal({ ...base, boundary: "z_max", reinforce: true }), /оси Z/);
});

test("whole-model reconstruction uses the same source-bound preview without a mirror", () => {
  const proposal = buildCadReconstructionProposal({
    sourceVersionId: "version-b",
    tolerance: "0.2",
    boundary: null,
    reinforce: false,
    reinforcementPercent: "20",
  });
  assert.equal(proposal.sourceVersionId, "version-b");
  assert.equal(proposal.body.restore_missing_half, null);
  assert.equal(proposal.body.reinforce_thickness_percent, null);
});

test("mirrored preview uses the selected bounding-box boundary on every axis", () => {
  assert.deepEqual(fragmentRestorationPreviewTransform("x_min", { x: 40, y: 30, z: 20 }), {
    axis: "x", mirrorScale: -1, mirrorOffsetMm: -40, planeOffsetMm: -20,
  });
  assert.deepEqual(fragmentRestorationPreviewTransform("y_max", { x: 40, y: 30, z: 20 }), {
    axis: "y", mirrorScale: -1, mirrorOffsetMm: 30, planeOffsetMm: 15,
  });
  assert.deepEqual(fragmentRestorationPreviewTransform("z_min", { x: 40, y: 30, z: 20 }), {
    axis: "z", mirrorScale: -1, mirrorOffsetMm: -20, planeOffsetMm: -10,
  });
  assert.throws(
    () => fragmentRestorationPreviewTransform("x_max", { x: 0, y: 30, z: 20 }),
    /положительный габарит/,
  );
});

test("mobile binds apply to the previewed version and waits for succeeded job", () => {
  const source = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
  const sheet = readFileSync(new URL("../src/FragmentRestorationSheet.tsx", import.meta.url), "utf8");

  assert.match(source, /proposal\.sourceVersionId !== active\.id/);
  assert.match(source, /client\.reconstruct\(proposal\.sourceVersionId, proposal\.body\)/);
  assert.match(source, /job\.status !== "succeeded"/);
  assert.match(source, /await headAfterJob\(job\)/);
  assert.match(source, /<FragmentRestorationSheet/);
  assert.match(source, /setCadReconstructionMode\("reconstruct"\)/);
  assert.match(sheet, /setProposal\(null\)/);
  assert.match(sheet, /не угадывает форму произвольной трещины/);
  assert.match(sheet, /задача ещё не запущена/);
  assert.match(sheet, /restorationPreview=\{proposal\.body\.restore_missing_half\}/);
  assert.match(sheet, /Это не серверный результат и не предсказанный контур скола/);
  const viewer = readFileSync(new URL("../src/ModelViewer.tsx", import.meta.url), "utf8");
  assert.match(viewer, /fragmentRestorationPreviewTransform\(restorationPreview, size\)/);
  assert.match(viewer, /mirrored\.position\[transform\.axis\] = transform\.mirrorOffsetMm/);
});
