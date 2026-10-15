/** Item 41: the text-to-house entry is reachable from the real house_design create flow and
 *  drives the real proposal → Apply/Cancel → existing house-box job path. Source-level checks:
 *  web tests have no DOM renderer, so they pin the wiring rather than simulate clicks. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { CREATE_SCENARIOS, getProjectGoal } from "@physical-ai/contracts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const page = read("../src/app/new/page.tsx");
const wizard = read("../src/components/HouseTextWizard.tsx");

test("house_design is a Create-menu scenario that opens the house picker", () => {
  assert.ok(CREATE_SCENARIOS.some((scenario) => scenario.goal === "house_design" && !scenario.route));
  assert.equal(getProjectGoal("house_design")?.id, "house_design");
  assert.match(page, /goal\?\.id === "house_design" && client/);
});

test("the house picker offers «По описанию» and renders the text wizard", () => {
  const picker = page.slice(page.indexOf("house-design-pick"));
  assert.match(picker, /onClick=\{\(\) => setHouseMode\("text"\)\}/);
  assert.match(picker, /"По описанию"/);
  assert.match(page, /if \(houseMode === "text"\) \{\s*return \(\s*<HouseTextWizard/);
});

test("the wizard proposes first, applies only the shown proposal and follows the job", () => {
  assert.match(wizard, /client\.proposeHouseFromText\(\{ workspace_id: workspaceId, prompt \}\)/);
  assert.match(wizard, /client\.applyHouseFromText\(\s*houseTextApplyBody\(proposal, proposedText\)/);
  assert.match(wizard, /client\.waitForJob\(accepted\.job\.job_id/);
  assert.match(wizard, /router\.push\(`\/projects\/\$\{accepted\.project_id\}\?goal=house_design`\)/);
  // Apply/Cancel exist only while a proposal is shown; editing the text drops the proposal.
  assert.match(wizard, /\{proposal \? \(\s*<span className="house-text-confirm">/);
  assert.match(wizard, /function edit\(value: string\) \{\s*setText\(value\);[\s\S]*?setProposal\(null\);/);
  assert.ok(wizard.indexOf("proposeHouseFromText") < wizard.indexOf("applyHouseFromText"));
  assert.doesNotMatch(wizard, /createAiCommand|buildHouseBox/);
});

test("the wizard speaks clear Russian", () => {
  for (const copy of ["Опишите дом", "Показать предложение", "Применить и создать дом", "Отмена", "Задание ещё не создано, AI не используется."]) {
    assert.ok(wizard.includes(copy), copy);
  }
});
