import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  hasExactFacade,
  isFacadeParameterCommand,
  shouldProposeFacadeCommand,
} from "../src/facade-command.ts";

const exactFacade = {
  provenance: {
    facade: {
      request: { wall_thickness_mm: 250, roof: { kind: "gable" } },
    },
  },
};

test("recognises the three supported exact-facade parameter families in RU and EN", () => {
  for (const prompt of [
    "Увеличь свес крыши на 200 мм",
    "Измени толщину стен до 300 мм",
    "Уменьши высоту крыши на 20 см",
    "Set roof overhang to 400 mm",
    "Increase wall thickness by 50 mm",
    "Decrease roof height by .2 m",
  ]) {
    assert.equal(isFacadeParameterCommand(prompt), true, prompt);
  }
  assert.equal(isFacadeParameterCommand("Добавь окно на южную стену"), false);
});

test("requires trusted facade lineage and an unscoped text-only command", () => {
  assert.equal(hasExactFacade(exactFacade), true);
  assert.equal(hasExactFacade({ provenance: { scan: { schema_version: 2 } } }), false);

  const base = {
    version: exactFacade,
    prompt: "Измени толщину стен до 300 мм",
    hasAttachments: false,
    hasSelection: false,
    hasRegion: false,
  };
  assert.equal(shouldProposeFacadeCommand(base), true);
  assert.equal(shouldProposeFacadeCommand({ ...base, hasAttachments: true }), false);
  assert.equal(shouldProposeFacadeCommand({ ...base, hasSelection: true }), false);
  assert.equal(shouldProposeFacadeCommand({ ...base, hasRegion: true }), false);
  assert.equal(
    shouldProposeFacadeCommand({ ...base, version: { provenance: { imported: true } } }),
    false,
  );
});

test("project composer uses read-only proposal before the explicit apply call", () => {
  const source = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

  assert.match(source, /client\.proposeFacadeCommand\(active!\.id, text\)/);
  assert.match(source, /client\.applyFacadeCommand\(details\.source_version_id/);
  assert.match(source, /expected_current_mm:\s*details\.current_value_mm/);
  assert.match(source, /proposed_new_mm:\s*details\.new_value_mm/);
  assert.match(source, /<FacadeCommandProposalSheet/);
});
