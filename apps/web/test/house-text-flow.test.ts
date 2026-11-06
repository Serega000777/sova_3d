/** Item 41: the text-to-house entry is reachable from the real house_design create flow and
 *  drives the real proposal → Apply/Cancel → existing house-box job path. Source-level checks:
 *  web tests have no DOM renderer, so they pin the wiring rather than simulate clicks. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { CREATE_SCENARIOS, getProjectGoal, houseTextFootprint } from "@physical-ai/contracts";

type HouseTextRequest = Parameters<typeof houseTextFootprint>[0];

function request(overrides: Partial<HouseTextRequest>): HouseTextRequest {
  return {
    length_mm: 12_000,
    width_mm: 8_000,
    floor_height_mm: 3_000,
    floors: 2,
    shape: "rectangle",
    ...overrides,
  };
}

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

test("copy credits rectangle, L and T shapes instead of claiming rectangle-only", () => {
  assert.match(wizard, /Поддерживаются прямоугольная, Г- и Т-образная массы/);
  assert.match(wizard, /Rectangular, L-shaped and T-shaped masses are supported/);
  assert.doesNotMatch(wizard, /One rectangular house without stairs/);
  assert.doesNotMatch(wizard, /Сейчас поддерживается один прямоугольный дом/);
});

test("the wizard validates the proposal is exact and renders the server footprint as a labelled massing diagram", () => {
  assert.match(wizard, /import \{[\s\S]*?houseTextFootprint[\s\S]*?\} from "@physical-ai\/contracts"/);
  assert.match(wizard, /import \{[\s\S]*?houseTextProposalIsExact[\s\S]*?\} from "@physical-ai\/contracts"/);
  assert.match(wizard, /houseTextProposalIsExact\(next, \{ workspaceId, projectId: null \}\)/);
  assert.match(wizard, /const footprint = proposal \? houseTextFootprint\(proposal\.request\) : null;/);
  assert.match(wizard, /<polygon\s+points=\{footprint\.map/);
  assert.match(wizard, /массы дома — не фасад|massing diagram — not a facade/);
  assert.match(wizard, /не фотореалистичный фасад|not a photoreal facade/);
});

test("a null footprint hides the diagram and fail-closed blocks apply (malformed dimensions / unsupported shape)", () => {
  assert.match(wizard, /\{footprint \? \(/);
  assert.match(wizard, /Сервер вернул неподдерживаемое пятно дома\./);
  assert.match(wizard, /The server returned an unsupported house footprint\./);
  assert.match(wizard, /onClick=\{\(\) => void apply\(\)\} disabled=\{busy !== null \|\| !footprint\}/);
  assert.match(wizard, /if \(!proposal \|\| proposedText === null \|\| !footprint\) return;/);
});

test("apply only completes navigation after the build job reports succeeded", () => {
  assert.match(wizard, /const job = await client\.waitForJob\(accepted\.job\.job_id/);
  assert.match(wizard, /if \(job\.status !== "succeeded"\) \{\s*throw new Error\(/);
  // The throw must precede the navigation so a failed job never opens a project.
  assert.ok(wizard.indexOf('if (job.status !== "succeeded")') < wizard.indexOf("router.push(`/projects/${accepted.project_id}"));
});

test("houseTextFootprint renders the exact canonical rectangle, L and T outlines the server would return", () => {
  const rectangle = houseTextFootprint(request({ shape: "rectangle", length_mm: 12_000, width_mm: 8_000 }));
  assert.deepEqual(rectangle, [[0, 0], [12_000, 0], [12_000, 8_000], [0, 8_000]]);

  const lShape = houseTextFootprint(request({ shape: "l_shape", length_mm: 12_000, width_mm: 8_000 }));
  assert.ok(lShape && lShape.length === 6, "L shape is a six-point outline");

  const tShape = houseTextFootprint(request({ shape: "t_shape", length_mm: 12_000, width_mm: 8_000 }));
  assert.ok(tShape && tShape.length === 8, "T shape is an eight-point outline");
});

test("houseTextFootprint fails closed on malformed dimensions and unsupported shapes", () => {
  assert.equal(houseTextFootprint(request({ length_mm: 500 })), null, "below the 2 m minimum");
  assert.equal(houseTextFootprint(request({ width_mm: 60_000 })), null, "above the 50 m maximum");
  assert.equal(houseTextFootprint(request({ length_mm: Number.NaN })), null, "non-finite length");
  assert.equal(
    houseTextFootprint(request({ shape: "circle" as unknown as HouseTextRequest["shape"] })),
    null,
    "unsupported shape",
  );
});
