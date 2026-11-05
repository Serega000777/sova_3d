import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  defaultSizeFamilyDraft,
  matchingSizeFamily,
  parseSizeFamilyDraft,
  sizeFamilyOutputMatches,
} from "../src/lib/size-family.ts";

const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");
const card = readFileSync(new URL("../src/components/SizeFamilyCard.tsx", import.meta.url), "utf8");

const validDraft = {
  S: { width: "75", depth: "40", height: "20" },
  M: { width: "100", depth: "40", height: "20" },
  L: { width: "125", depth: "40", height: "20" },
};

test("reference 81 proposes width-only 75/100/125 percent and parses the complete RU/EN table atomically", () => {
  assert.deepEqual(defaultSizeFamilyDraft({ x: 100, y: 40, z: 20 }), validDraft);
  assert.deepEqual(parseSizeFamilyDraft({
    ...validDraft,
    S: { width: "0,001", depth: "10 000".replace(" ", ""), height: "1.2345" },
  }), [
    { label: "S", widthMm: 0.001, depthMm: 10_000, heightMm: 1.235 },
    { label: "M", widthMm: 100, depthMm: 40, heightMm: 20 },
    { label: "L", widthMm: 125, depthMm: 40, heightMm: 20 },
  ]);
  assert.equal(parseSizeFamilyDraft({ ...validDraft, S: { ...validDraft.S, width: "0" } }), null);
  assert.equal(parseSizeFamilyDraft({ ...validDraft, M: { ...validDraft.M, depth: "10000.001" } }), null);
  assert.equal(parseSizeFamilyDraft({ ...validDraft, L: { ...validDraft.L, height: "NaN" } }), null);
});

test("verified preview dimensions and an identical lost-response retry fail closed", () => {
  const preset = { label: "S" as const, widthMm: 75, depthMm: 40, heightMm: 20 };
  assert.equal(sizeFamilyOutputMatches([75.009, 39.991, 20], preset), true);
  assert.equal(sizeFamilyOutputMatches([75.02, 40, 20], preset), false);
  assert.equal(sizeFamilyOutputMatches([75, 40], preset), false);

  const family = {
    id: "family-81",
    project_id: "project-81",
    source_version_id: "source-81",
    selected_label: "M",
    created_at: "2026-11-05T00:00:00Z",
    members: [
      { label: "S", version_id: "small-81", width_mm: 75, depth_mm: 40, height_mm: 20 },
      { label: "M", version_id: "medium-81", width_mm: 100, depth_mm: 40, height_mm: 20 },
      { label: "L", version_id: "large-81", width_mm: 125, depth_mm: 40, height_mm: 20 },
    ],
  } as const;
  const requestMembers = family.members.map(({ label, version_id }) => ({ label, version_id }));
  assert.equal(matchingSizeFamily([family] as never, "source-81", requestMembers), family);
  assert.equal(matchingSizeFamily([family] as never, "other-source", requestMembers), null);
  assert.equal(matchingSizeFamily([family] as never, "source-81", requestMembers.slice(0, 2)), null);
  assert.match(studio, /recovered \?\? await client\.createSizeFamily\(projectId, body\)/);
});

test("saved family loading and mutations are guarded by a version context and revision", () => {
  assert.match(studio, /const sizeFamilyContext = \[projectId, activeVersionId \?\? ""\]\.join\("\|"\)/);
  const loader = studio.slice(
    studio.indexOf("const revision = sizeFamilyRevision.current + 1"),
    studio.indexOf("setEngineeringHistory([])"),
  );
  assert.match(loader, /setSizeFamily\(null\)/);
  assert.match(loader, /client[\s\S]*?\.listSizeFamilies\(projectId\)/);
  assert.match(loader, /sizeFamilyRevision\.current !== revision/);
  assert.match(loader, /sizeFamilyContextRef\.current !== context/);
  assert.match(studio, /\[client, projectId, activeVersionId, sizeFamilyContext\]/);
  const builder = studio.slice(studio.indexOf("async function buildSizeFamily"), studio.indexOf("async function applyDimensions"));
  assert.match(builder, /const revision = sizeFamilyRevision\.current/);
  assert.match(builder, /const context = sizeFamilyContext/);
  assert.match(builder, /sizeFamilyRevision\.current === revision/);
  assert.match(builder, /sizeFamilyContextRef\.current === context/);
});

test("switching S M L sends the family id and clicked label then opens that exact member version", () => {
  const selector = studio.slice(
    studio.indexOf("async function selectSizeFamilyMember"),
    studio.indexOf("async function applyDimensions"),
  );
  assert.match(selector, /client\.selectSizeFamilyMember\(projectId, family\.id, label\)/);
  assert.match(selector, /selected\.members\.find\(\(item\) => item\.label === label\)/);
  assert.match(selector, /client\.getVersion\(member\.version_id\)/);
  assert.match(card, /select\(member\.label\)/);
  assert.match(card, /onInspect\(member\.version_id\)/);
});

test("the web card gates building and project-head changes while retaining read-only inspection", () => {
  assert.match(card, /canBuild && draft \? \(/);
  assert.match(card, /\{canSelect \? \(/);
  assert.match(card, /onClick=\{\(\) => onInspect\(member\.version_id\)\}/);
  assert.match(studio, /canBuild=\{canEditProject && !hasExplicitScene\}/);
  assert.match(studio, /canSelect=\{canEditProject\}/);
  assert.match(studio, /preview: true/);
  assert.match(studio, /completed\.map\(\(item\) => \(\{ label: item\.label, version_id: item\.versionId \}\)\)/);
});
