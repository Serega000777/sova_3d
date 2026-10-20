import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/HouseTextCreator.tsx", import.meta.url), "utf8");
const projects = readFileSync(new URL("../app/(tabs)/projects.tsx", import.meta.url), "utf8");

test("mobile text-to-house keeps proposal read-only until explicit apply", () => {
  assert.match(source, /client\.proposeHouseFromText\(\{ workspace_id: workspaceId, prompt \}\)/);
  assert.match(source, /client\.applyHouseFromText\(/);
  assert.match(source, /houseTextApplyBody\(proposal, proposedText\)/);
  assert.match(source, /client\.waitForJob\(accepted\.job\.job_id/);
  assert.match(source, /if \(job\.status !== "succeeded"\)/);
});

test("editing the prompt invalidates the exact server proposal", () => {
  assert.match(source, /function edit\(value: string\)[\s\S]*setProposal\(null\)/);
  assert.match(source, /function edit\(value: string\)[\s\S]*setProposedText\(null\)/);
  assert.match(source, /if \(!proposal \|\| proposedText === null \|\| busy\) return/);
  assert.match(source, /editable=\{busy === null\}/);
  assert.match(source, /disabled=\{busy !== null\} onPress=\{onBack\}/);
});

test("house-design scenario exposes the mobile creator and routes to the immutable project", () => {
  assert.match(projects, /goal\.id === "house_design"/);
  assert.match(projects, /<HouseTextCreator/);
  assert.match(projects, /houseMode === "text"/);
  assert.match(projects, /houseMode === "blank"/);
  assert.match(projects, /router\.push\(`\/project\/\$\{projectId\}\?goal=house_design`\)/);
});
