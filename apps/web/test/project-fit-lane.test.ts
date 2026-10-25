import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { ProjectSummary } from "@physical-ai/contracts";

import { projectEnvelope } from "../src/lib/project-envelope.ts";

const base = {
  id: "00000000-0000-0000-0000-000000000001",
  workspace_id: "00000000-0000-0000-0000-000000000002",
  name: "Exact project",
  description: null,
  units: "mm",
  head_version_id: "00000000-0000-0000-0000-000000000003",
  created_at: "2026-10-25T00:00:00Z",
  updated_at: "2026-10-25T00:00:00Z",
  head_version: {
    id: "00000000-0000-0000-0000-000000000003",
    project_id: "00000000-0000-0000-0000-000000000001",
    parent_version_id: null,
    sequence_no: 1,
    state: "finalized",
    label: null,
    created_by: null,
    created_at: "2026-10-25T00:00:00Z",
    finalized_at: "2026-10-25T00:00:00Z",
    assets: [],
  },
} satisfies Omit<ProjectSummary, "head_version"> & { head_version: Omit<NonNullable<ProjectSummary["head_version"]>, "provenance"> };

function projectWith(body: unknown): ProjectSummary {
  return {
    ...base,
    head_version: { ...base.head_version, provenance: { bodies: [body] } },
  };
}

test("project fit uses only a finite positive valid head envelope", () => {
  assert.deepEqual(projectEnvelope(projectWith({ valid: true, bbox_mm: { size: [40, 20, 8] } })), [40, 20, 8]);
  assert.equal(projectEnvelope(projectWith({ valid: false, bbox_mm: { size: [40, 20, 8] } })), null);
  assert.equal(projectEnvelope(projectWith({ valid: true, bbox_mm: { size: [40, 0, 8] } })), null);
  assert.equal(projectEnvelope(projectWith({ valid: true, bbox_mm: { size: [40, 20] } })), null);
});

test("the project lane reuses measured fit without claiming recommendation or collision proof", () => {
  const page = readFileSync(new URL("../src/app/market/page.tsx", import.meta.url), "utf8");
  assert.match(page, /client\.listProjects\(session\.workspaceId\)/);
  assert.match(page, /client\.getProject\(fitProjectId\)/);
  assert.match(page, /max_width_mm: envelope\[0\]/);
  assert.match(page, /max_depth_mm: envelope\[1\]/);
  assert.match(page, /max_height_mm: envelope\[2\]/);
  assert.match(page, /rotate_to_fit: true/);
  assert.match(page, /размерный shortlist[\s\S]*?не рекомендация/);
  assert.doesNotMatch(page, /AI recommends|ИИ рекомендует/);
});
