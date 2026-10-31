import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  currentAnimationCommandProposal,
  verifiedAnimationCommandProposal,
  verifiedAppliedAnimationVersionId,
} from "../src/animation-command.ts";

const sourceVersionId = "11111111-1111-4111-8111-111111111111";
const nextVersionId = "22222222-2222-4222-8222-222222222222";
const value = {
  clip: {
    schema_version: 1,
    kind: "rigid_joint_clip",
    joint_type: "revolute",
    node_id: "lid",
    duration_seconds: 2,
    direction: "reverse",
  },
  language: "ru",
  job_created: false,
  ai_used: false,
};

test("mobile binds only an honest bounded proposal to the exact source text and version", () => {
  const bound = verifiedAnimationCommandProposal(value, sourceVersionId, "  закрой за 2 секунды  ");
  assert.ok(bound);
  assert.equal(bound.prompt, "закрой за 2 секунды");
  assert.equal(currentAnimationCommandProposal(bound, sourceVersionId, "закрой за 2 секунды"), value);
  assert.equal(currentAnimationCommandProposal(bound, nextVersionId, "закрой за 2 секунды"), null);
  assert.equal(currentAnimationCommandProposal(bound, sourceVersionId, "открой за 2 секунды"), null);
  assert.equal(verifiedAnimationCommandProposal({ ...value, ai_used: true }, sourceVersionId, "закрой"), null);
  assert.equal(verifiedAnimationCommandProposal({ ...value, job_created: true }, sourceVersionId, "закрой"), null);
  assert.equal(verifiedAnimationCommandProposal({ ...value, clip: { ...value.clip, duration_seconds: 61 } }, sourceVersionId, "закрой"), null);
  assert.equal(verifiedAnimationCommandProposal({ ...value, clip: { ...value.clip, direction: "sideways" } }, sourceVersionId, "закрой"), null);
});

test("mobile accepts only a new immutable version carrying the exact proposed clip", () => {
  const bound = verifiedAnimationCommandProposal(value, sourceVersionId, "закрой за 2 секунды");
  assert.ok(bound);
  assert.equal(verifiedAppliedAnimationVersionId({ version_id: nextVersionId, clip: value.clip }, bound), nextVersionId);
  assert.equal(verifiedAppliedAnimationVersionId({ version_id: sourceVersionId, clip: value.clip }, bound), null);
  assert.equal(verifiedAppliedAnimationVersionId({ version_id: nextVersionId, clip: { ...value.clip, direction: "forward" } }, bound), null);
});

test("mobile mechanism UI reaches proposal and apply with stale-response guards", () => {
  const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
  const card = readFileSync(new URL("../src/AnimationCommandCard.tsx", import.meta.url), "utf8");
  assert.match(project, /client\.proposeAnimationCommand\(sourceVersionId, normalizedPrompt\)/);
  assert.match(project, /activeIdRef\.current !== sourceVersionId/);
  assert.match(project, /setAnimationProposal\(null\);\n  }, \[activeId\]\)/);
  assert.match(project, /client\.applyAnimationCommand\(bound\.sourceVersionId, bound\.prompt, bound\.value\.clip\)/);
  assert.match(project, /verifiedAppliedAnimationVersionId\(applied, bound\)/);
  assert.match(card, /открой за 2 секунды/);
  assert.match(card, /закрой за 2 секунды/);
  assert.match(card, /Предложение только для чтения/);
  assert.match(card, /Применить к новой версии/);
});
