import assert from "node:assert/strict";
import test from "node:test";

import { latestRestorableLocalEditDraft, restorableLocalEditDraft } from "../src/local-edit-draft.ts";

const version = (overrides: Record<string, unknown> = {}) => ({
  id: "draft-1",
  project_id: "project-1",
  parent_version_id: "source-1",
  sequence_no: 2,
  state: "draft",
  label: null,
  created_by: null,
  created_at: "2026-11-22T00:00:00Z",
  finalized_at: null,
  assets: [],
  provenance: {
    operation: "ai_command",
    ai_request_id: "request-1",
    local_edit: {
      schema_version: 1,
      ai_request_id: "request-1",
      source_version_id: "source-1",
      command: "Добавь здесь отверстие Ø6 мм",
      region: {
        region: { kind: "box", min_mm: [1, 2, 3], max_mm: [4, 5, 6] },
        target: "body",
        surface_axis: "z",
        surface_sign: "+",
      },
    },
  },
  ...overrides,
}) as any;

test("restores only an exact server-bound local-edit draft", () => {
  const restored = restorableLocalEditDraft(version());
  assert.equal(restored?.sourceVersionId, "source-1");
  assert.equal(restored?.command, "Добавь здесь отверстие Ø6 мм");
  assert.deepEqual(restored?.region.region, { kind: "box", min_mm: [1, 2, 3], max_mm: [4, 5, 6] });
});

test("fails closed for substituted identity, malformed region, or finalized output", () => {
  const substituted = version();
  substituted.provenance.local_edit.ai_request_id = "request-2";
  assert.equal(restorableLocalEditDraft(substituted), null);
  const malformed = version();
  malformed.provenance.local_edit.region.region.max_mm = [0, 5, 6];
  assert.equal(restorableLocalEditDraft(malformed), null);
  assert.equal(restorableLocalEditDraft(version({ state: "finalized" })), null);
});

test("chooses the newest valid unresolved local edit", () => {
  const newest = version({ id: "draft-3", sequence_no: 3 });
  assert.equal(latestRestorableLocalEditDraft([version(), newest])?.version.id, "draft-3");
});
