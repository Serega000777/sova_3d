import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { verifiedAssemblyGuideProgress } from "../src/assembly-guide-progress.ts";
import { mechanismAssemblyGuide } from "../src/mechanism-assembly-guide.ts";

const hinge = {
  kind: "hinged_lid",
  joint: { type: "revolute", node_id: "lid", axis: "x", pivot_mm: [0, 0, 12], min_angle_deg: 0, max_angle_deg: 110 },
  parts: { base: "base", lid: "lid", pin: "pin" },
};
const bom = (...ids) => ids.map((id) => ({
  source_node_id: id,
  name: id === "pin" ? "Removable pin" : id,
  resolved_asset_id: `asset-${id}`,
  quantity: 1,
  visible_quantity: 1,
  node_ids: [id],
}));

test("mobile guide is bound to the exact visible mechanism parts", () => {
  const guide = mechanismAssemblyGuide(
    { build_hinged_lid: hinge },
    new Set(["base", "lid", "pin"]),
    bom("base", "lid", "pin"),
  );
  assert.equal(guide?.kind, "hinged_lid");
  assert.deepEqual(guide?.steps.map((step) => step.id), ["inspect-parts", "align-hinge", "insert-pin", "verify-motion"]);
  assert.deepEqual(guide?.steps[2]?.nodeIds, ["pin"]);
  assert.match(guide?.steps[3]?.detailRu ?? "", /0° до 110°/);
  assert.deepEqual(guide?.bom.map((item) => [item.sourceNodeId, item.quantity]), [
    ["base", 1], ["lid", 1], ["pin", 1],
  ]);

  const sliding = mechanismAssemblyGuide({
    build_sliding_lid: {
      kind: "sliding_lid",
      joint: { type: "prismatic", node_id: "slide-lid", axis: "y", min_travel_mm: 0, max_travel_mm: 55 },
      parts: { base: "slide-base", lid: "slide-lid" },
    },
  }, new Set(["slide-base", "slide-lid"]), bom("slide-base", "slide-lid"));
  assert.deepEqual(sliding?.steps.map((step) => step.id), ["inspect-parts", "align-guides", "seat-lid", "verify-motion"]);
  assert.match(sliding?.steps[3]?.detailEn ?? "", /0–55 mm/);

  const instancedBase = mechanismAssemblyGuide({
    build_sliding_lid: {
      kind: "sliding_lid",
      joint: { type: "prismatic", node_id: "slide-lid", axis: "y", min_travel_mm: 0, max_travel_mm: 55 },
      parts: { base: "slide-base", lid: "slide-lid" },
    },
  }, new Set(["slide-base", "slide-base-copy", "slide-lid"]), [
    {
      source_node_id: "slide-base",
      name: "Guided base",
      resolved_asset_id: "asset-slide-base",
      quantity: 2,
      visible_quantity: 2,
      node_ids: ["slide-base", "slide-base-copy"],
    },
    ...bom("slide-lid"),
  ]);
  assert.equal(instancedBase?.bom[0]?.quantity, 2);
});

test("mobile guide fails closed for hidden, conflicting or substituted parts", () => {
  assert.equal(mechanismAssemblyGuide({ build_hinged_lid: hinge }, new Set(["base", "lid"]), bom("base", "lid", "pin")), null);
  assert.equal(mechanismAssemblyGuide({
    build_hinged_lid: { ...hinge, parts: { base: "base", lid: "other-lid", pin: "pin" } },
  }, new Set(["base", "lid", "other-lid", "pin"]), bom("base", "lid", "other-lid", "pin")), null);
  assert.equal(mechanismAssemblyGuide({
    build_hinged_lid: { ...hinge, parts: { base: "base", lid: "lid", pin: "lid" } },
  }, new Set(["base", "lid"]), bom("base", "lid")), null);
  assert.equal(mechanismAssemblyGuide({
    build_hinged_lid: hinge,
    build_sliding_lid: { kind: "sliding_lid", joint: { type: "prismatic", node_id: "lid", axis: "y" } },
  }, new Set(["base", "lid", "pin"]), bom("base", "lid", "pin")), null);
  assert.equal(mechanismAssemblyGuide(
    { build_hinged_lid: hinge },
    new Set(["base", "lid", "pin"]),
    bom("base", "lid"),
  ), null);
  assert.equal(mechanismAssemblyGuide(
    { build_hinged_lid: hinge },
    new Set(["base", "lid", "pin"]),
    [...bom("base", "lid", "pin"), ...bom("pin")],
  ), null);
});

test("shared guide progress stays bound to the exact version, kind and known steps", () => {
  const guide = mechanismAssemblyGuide(
    { build_hinged_lid: hinge },
    new Set(["base", "lid", "pin"]),
    bom("base", "lid", "pin"),
  );
  assert.ok(guide);
  const verified = verifiedAssemblyGuideProgress({
    version_id: "version-69",
    guide_kind: "hinged_lid",
    completed_step_ids: ["inspect-parts", "insert-pin"],
    revision: 3,
    updated_at: null,
    updated_by: null,
  }, "version-69", guide);
  assert.deepEqual([...verified.completed], ["inspect-parts", "insert-pin"]);
  assert.equal(verified.revision, 3);
  assert.equal(verifiedAssemblyGuideProgress({
    version_id: "substituted",
    guide_kind: "hinged_lid",
    completed_step_ids: [],
    revision: 0,
    updated_at: null,
    updated_by: null,
  }, "version-69", guide), null);
  assert.equal(verifiedAssemblyGuideProgress({
    version_id: "version-69",
    guide_kind: "sliding_lid",
    completed_step_ids: [],
    revision: 0,
    updated_at: null,
    updated_by: null,
  }, "version-69", guide), null);
  assert.equal(verifiedAssemblyGuideProgress({
    version_id: "version-69",
    guide_kind: "hinged_lid",
    completed_step_ids: ["inspect-parts", "inspect-parts"],
    revision: 1,
    updated_at: null,
    updated_by: null,
  }, "version-69", guide), null);
  assert.equal(verifiedAssemblyGuideProgress({
    version_id: "version-69",
    guide_kind: "hinged_lid",
    completed_step_ids: ["unknown"],
    revision: 1,
    updated_at: null,
    updated_by: null,
  }, "version-69", guide), null);
});

test("project screen renders the version-scoped guide and connects part selection", () => {
  const source = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
  const card = readFileSync(new URL("../src/AssemblyGuideCard.tsx", import.meta.url), "utf8");
  assert.match(source, /mechanismAssemblyGuide/);
  assert.match(source, /<AssemblyGuideCard/);
  assert.match(source, /versionId=\{activeId \?\? ""\}/);
  assert.match(source, /onSelectNode=\{\(nodeId\) =>/);
  assert.match(source, /setSelectedSceneNodeId\(nodeId\)/);
  assert.match(source, /\.inspectAssembly\(activeId\)/);
  assert.match(source, /editable=\{canEditWorkspace\}/);
  assert.match(card, /getAssemblyGuideProgress\(versionId\)/);
  assert.match(card, /putAssemblyGuideProgress\(versionId/);
  assert.match(card, /expected_revision: revision/);
  assert.match(card, /reason instanceof ApiError && reason\.status === 409/);
  assert.match(card, /if \(requestRevision\.current === request\) \{\s+setSyncError/);
  assert.doesNotMatch(card, /AsyncStorage/);
  assert.match(card, /accessibilityRole="checkbox"/);
  assert.match(card, /синхронизируются для этой версии между участниками workspace/);
  assert.match(card, /Ведомость деталей инструкции/);
});
