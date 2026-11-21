import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { buildFragmentRestorationProposal } from "../src/lib/fragment-restoration.ts";

const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("reference 73 builds an exact source-bound non-mutating plan", () => {
  assert.deepEqual(buildFragmentRestorationProposal({
    sourceVersionId: "version-1",
    toleranceMm: 0.2,
    boundary: "x_min",
    reinforce: true,
    reinforcementPercent: 20,
  }), {
    sourceVersionId: "version-1",
    body: {
      tolerance_mm: 0.2,
      threads: true,
      restore_missing_half: "x_min",
      reinforce_thickness_percent: 20,
    },
  });
});

test("restoration proposal rejects unsafe tolerance reinforcement and Z combination", () => {
  const base = {
    sourceVersionId: "version-1",
    toleranceMm: 0.2,
    boundary: "x_min" as const,
    reinforce: false,
    reinforcementPercent: 20,
  };
  assert.throws(() => buildFragmentRestorationProposal({ ...base, toleranceMm: 0.01 }));
  assert.throws(() => buildFragmentRestorationProposal({ ...base, toleranceMm: 5.01 }));
  assert.throws(() => buildFragmentRestorationProposal({ ...base, reinforce: true, reinforcementPercent: 51 }));
  assert.throws(() => buildFragmentRestorationProposal({ ...base, boundary: "z_max", reinforce: true }));
});

test("web invalidates preview inputs and starts reconstruction only from explicit apply", () => {
  assert.match(studio, /setReconstructionProposal\(null\)/);
  assert.match(studio, /proposal\.sourceVersionId !== activeVersion\.id/);
  assert.match(studio, /client\.reconstruct\(proposal\.sourceVersionId, proposal\.body\)/);
  assert.match(studio, /result\.source_version_id !== proposal\.sourceVersionId/);
  assert.match(studio, /child\.parent_version_id !== proposal\.sourceVersionId/);
  assert.match(studio, /activeVersionIdRef\.current === proposal\.sourceVersionId/);
  assert.match(studio, /План готов — задача ещё не запущена/);
  assert.match(studio, /Применить как новую версию/);
});
