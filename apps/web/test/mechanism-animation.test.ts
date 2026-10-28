import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  hingedLidTransform,
  mechanismAssemblyGuide,
  mechanismPlaybackValue,
  sceneMechanism,
  slidingLidTransform,
} from "../src/lib/mechanism.ts";

test("joint playback follows only its bounded persisted range", () => {
  assert.equal(mechanismPlaybackValue(0, 110, 0), 0);
  assert.equal(mechanismPlaybackValue(0, 110, 0.5), 55);
  assert.equal(mechanismPlaybackValue(0, 110, 2), 110);
  assert.equal(mechanismPlaybackValue(10, 55, -1), 10);
  assert.equal(mechanismPlaybackValue(10, 55, Number.NaN), 10);
});

test("hinged lid preview rotates around its declared X-axis pivot", () => {
  const seat = [
    [1, 0, 0, 0],
    [0, 1, 0, 4],
    [0, 0, 1, 18],
    [0, 0, 0, 1],
  ];
  const closed = hingedLidTransform(seat, 0, 0, 110);
  assert.deepEqual(closed, seat);
  const open = hingedLidTransform(seat, 90, 0, 110);
  assert.ok(Math.abs(open[1]![1]!) < 1e-10);
  assert.equal(open[1]![2], -1);
  assert.equal(open[1]![3], 4);
  assert.equal(open[2]![1], 1);
  assert.equal(open[2]![3], 18);
  assert.deepEqual(hingedLidTransform(seat, 500, 10, 90), open);
});

test("Studio exposes generation and bounded kinematic validation", () => {
  const source = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");
  assert.match(source, /client\.buildHingedLid/);
  assert.match(source, /type="range"/);
  assert.match(source, /requestAnimationFrame\(tick\)/);
  assert.match(source, /Воспроизвести движение/);
  assert.match(source, /один сохранённый joint/);
  assert.match(source, /Прочность, износ/);
});

const SEAT = [
  [1, 0, 0, 0],
  [0, 1, 0, 3.3],
  [0, 0, 1, 30],
  [0, 0, 0, 1],
];

test("sliding lid preview translates along its own +Y inside the declared travel", () => {
  assert.deepEqual(slidingLidTransform(SEAT, 0, 0, 55), SEAT);
  const open = slidingLidTransform(SEAT, 40, 0, 55);
  assert.equal(open[1]![3], 43.3);
  assert.equal(open[2]![3], 30);
  assert.equal(slidingLidTransform(SEAT, 500, 0, 55)[1]![3], 58.3);
  assert.equal(slidingLidTransform(SEAT, -10, 0, 55)[1]![3], 3.3);
  assert.equal(slidingLidTransform(SEAT, Number.NaN, 0, 55)[1]![3], 3.3);
  // the source matrix is never mutated
  assert.equal(SEAT[1]![3], 3.3);
});

test("sliding preview matches the exported glTF translation keys (metres, Y-up)", () => {
  // the worker keys t + R·s·(d·Y); R·s maps platform (x, y, z) mm to glTF (x, z, -y) m
  const toGltf = (matrix: number[][]) => [matrix[0]![3]! / 1000, matrix[2]![3]! / 1000, -matrix[1]![3]! / 1000];
  const turned = [
    [0, -1, 0, 0],
    [1, 0, 0, 3.3],
    [0, 0, 1, 30],
    [0, 0, 0, 1],
  ];
  const closedKey = toGltf(slidingLidTransform(SEAT, 0, 0, 55));
  const openKey = toGltf(slidingLidTransform(SEAT, 55, 0, 55));
  assert.ok(Math.abs(closedKey[1]! - 0.03) < 1e-12 && Math.abs(closedKey[2]! + 0.0033) < 1e-12);
  assert.ok(Math.abs(openKey[2]! - closedKey[2]! + 0.055) < 1e-12);
  // a turned group slides along its own guides, as the GLB channel does
  const turnedOpen = toGltf(slidingLidTransform(turned, 55, 0, 55));
  assert.ok(Math.abs(turnedOpen[0]! + 0.055) < 1e-12);
});

const SLIDE = {
  kind: "sliding_lid",
  joint: { type: "prismatic", node_id: "slide_lid_a", axis: "y", min_travel_mm: 0, max_travel_mm: 55 },
};
const HINGE = {
  kind: "hinged_lid",
  joint: { type: "revolute", node_id: "hinge_lid_a", axis: "x", pivot_mm: [0, 0, 18], max_angle_deg: 110 },
};
const VISIBLE = new Set(["slide_lid_a", "hinge_lid_a"]);
const assemblyBom = (...ids: string[]) => ids.map((id) => ({
  source_node_id: id,
  name: id,
  resolved_asset_id: `asset-${id}`,
  quantity: 1,
  visible_quantity: 1,
  node_ids: [id],
}));

test("scene mechanism follows the export rule: one trusted visible joint or nothing", () => {
  assert.deepEqual(sceneMechanism({ build_sliding_lid: SLIDE }, VISIBLE), {
    kind: "sliding_lid",
    nodeId: "slide_lid_a",
    minTravelMm: 0,
    maxTravelMm: 55,
  });
  assert.deepEqual(sceneMechanism({ build_hinged_lid: HINGE }, VISIBLE), {
    kind: "hinged_lid",
    nodeId: "hinge_lid_a",
    minAngleDeg: 0,
    maxAngleDeg: 110,
  });
  assert.equal(sceneMechanism({ build_sliding_lid: SLIDE, build_hinged_lid: HINGE }, VISIBLE), null);
  assert.equal(sceneMechanism({ build_sliding_lid: SLIDE }, new Set(["hinge_lid_a"])), null);
  assert.equal(sceneMechanism({ build_hinged_lid: { ...HINGE, joint: { ...HINGE.joint, axis: "y" } } }, VISIBLE), null);
  const broken = (joint: Record<string, unknown>) => ({ build_sliding_lid: { ...SLIDE, joint: { ...SLIDE.joint, ...joint } } });
  for (const joint of [{ type: "revolute" }, { axis: "x" }, { max_travel_mm: "55" }, { max_travel_mm: -1 }, { max_travel_mm: Infinity }]) {
    assert.equal(sceneMechanism(broken(joint), VISIBLE), null, JSON.stringify(joint));
  }
  assert.equal(sceneMechanism({}, VISIBLE), null);
});

test("Studio offers the sliding lid with bounded travel and honest wording", () => {
  const source = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");
  assert.match(source, /client\.buildSlidingLid/);
  assert.match(source, /client\.buildHingedLid/);
  assert.match(source, /slidingLidTransform\(part\.worldTransform/);
  assert.match(source, /max=\{max\}/);
  assert.match(source, /прочность, износ, трение и реальная посадка подтверждаются физической печатью/);
  assert.match(source, /strength, wear, friction and real fit require a physical test/);
  // never a strength, certification or AI claim for the generated mechanism
  const panel = source.slice(source.indexOf('{tool === "mechanism" && ('), source.indexOf('{tool === "site" && ('));
  assert.doesNotMatch(panel, /гарантир|сертифиц|выдерживает|guarantee|certified|load rating/i);
  assert.doesNotMatch(panel, /(^|[^A-Za-z])AI([^A-Za-z]|$)|ИИ/);
});

test("assembly guide is bound to the exact persisted mechanism parts", () => {
  const hinged = mechanismAssemblyGuide({
    build_hinged_lid: {
      ...HINGE,
      parts: { base: "hinge_base_a", lid: "hinge_lid_a", pin: "hinge_pin_a" },
    },
  }, new Set(["hinge_base_a", "hinge_lid_a", "hinge_pin_a"]), assemblyBom(
    "hinge_base_a", "hinge_lid_a", "hinge_pin_a",
  ));
  assert.equal(hinged?.kind, "hinged_lid");
  assert.deepEqual(hinged?.steps.map((step) => step.id), [
    "inspect-parts",
    "align-hinge",
    "insert-pin",
    "verify-motion",
  ]);
  assert.deepEqual(hinged?.steps[2]?.nodeIds, ["hinge_pin_a"]);
  assert.match(hinged?.steps[3]?.detailRu ?? "", /110°/);
  assert.deepEqual(hinged?.bom.map((item) => [item.sourceNodeId, item.quantity]), [
    ["hinge_base_a", 1],
    ["hinge_lid_a", 1],
    ["hinge_pin_a", 1],
  ]);

  const sliding = mechanismAssemblyGuide({
    build_sliding_lid: {
      ...SLIDE,
      parts: { base: "slide_base_a", lid: "slide_lid_a" },
    },
  }, new Set(["slide_base_a", "slide_lid_a"]), assemblyBom("slide_base_a", "slide_lid_a"));
  assert.deepEqual(sliding?.steps.map((step) => step.id), [
    "inspect-parts",
    "align-guides",
    "seat-lid",
    "verify-motion",
  ]);
  assert.match(sliding?.steps[3]?.detailEn ?? "", /0–55 mm/);

  const instancedBase = mechanismAssemblyGuide({
    build_sliding_lid: {
      ...SLIDE,
      parts: { base: "slide_base_a", lid: "slide_lid_a" },
    },
  }, new Set(["slide_base_a", "slide_lid_a", "slide_base_copy"]), [
    {
      source_node_id: "slide_base_a",
      name: "Guided base",
      resolved_asset_id: "asset-slide-base",
      quantity: 2,
      visible_quantity: 2,
      node_ids: ["slide_base_a", "slide_base_copy"],
    },
    ...assemblyBom("slide_lid_a"),
  ]);
  assert.equal(instancedBase?.bom[0]?.quantity, 2);
});

test("assembly guide fails closed for missing, conflicting or substituted part ids", () => {
  const valid = {
    build_hinged_lid: {
      ...HINGE,
      parts: { base: "hinge_base_a", lid: "hinge_lid_a", pin: "hinge_pin_a" },
    },
  };
  const hingedBom = assemblyBom("hinge_base_a", "hinge_lid_a", "hinge_pin_a");
  assert.equal(mechanismAssemblyGuide(valid, new Set(["hinge_base_a", "hinge_lid_a"]), hingedBom), null);
  assert.equal(mechanismAssemblyGuide({
    build_hinged_lid: {
      ...HINGE,
      parts: { base: "hinge_base_a", lid: "other_lid", pin: "hinge_pin_a" },
    },
  }, new Set(["hinge_base_a", "hinge_lid_a", "hinge_pin_a", "other_lid"]), [
    ...hingedBom, ...assemblyBom("other_lid"),
  ]), null);
  assert.equal(mechanismAssemblyGuide({
    build_hinged_lid: {
      ...HINGE,
      parts: { base: "hinge_base_a", lid: "hinge_lid_a", pin: "hinge_lid_a" },
    },
  }, new Set(["hinge_base_a", "hinge_lid_a"]), hingedBom), null);
  assert.equal(mechanismAssemblyGuide({ ...valid, build_sliding_lid: SLIDE }, new Set([
    "hinge_base_a", "hinge_lid_a", "hinge_pin_a", "slide_lid_a",
  ]), hingedBom), null);
  assert.equal(mechanismAssemblyGuide(
    valid,
    new Set(["hinge_base_a", "hinge_lid_a", "hinge_pin_a"]),
    assemblyBom("hinge_base_a", "hinge_lid_a"),
  ), null);
  assert.equal(mechanismAssemblyGuide(
    valid,
    new Set(["hinge_base_a", "hinge_lid_a", "hinge_pin_a"]),
    [...hingedBom, ...assemblyBom("hinge_pin_a")],
  ), null);
});

test("Studio renders a version-scoped assembly guide without claiming photos or completion", () => {
  const source = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");
  assert.match(source, /mechanismAssemblyGuide/);
  assert.match(source, /Инструкция по сборке этой версии/);
  assert.match(source, /Детали сцены/);
  assert.match(source, /\.inspectAssembly\(activeVersionId\)/);
  assert.match(source, /Ведомость деталей инструкции/);
  assert.match(source, /Фотографии, крепёж вне сцены и отметки выполнения не добавлены/);
});
