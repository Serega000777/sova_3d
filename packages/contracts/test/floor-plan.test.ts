/** T-237: plan geometry, annotation hit-testing/moving and undo/redo. */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  type Annotation,
  cloudPath,
  commit,
  distanceBetween,
  formatLength,
  hitTest,
  moveAnnotation,
  newHistory,
  nextPinNumber,
  parseAnnotations,
  parseFloorPlan,
  planBounds,
  rectangularRoom,
  redo,
  roomArea,
  sampleHouse,
  undo,
  wallLength,
} from "../src/floor-plan.ts";

const base = { author: "A", created_at: "2026-10-01T00:00:00Z", status: "open" as const, note: "", colour: "#ff4d4f" };
const pin = (id: string, number: number, at: [number, number]): Annotation => ({ ...base, id, kind: "pin", number, at });

test("a rectangular room has four walls, correct area and a door and a window", () => {
  const plan = rectangularRoom(4000, 5000, "Studio");
  assert.equal(plan.walls.length, 4);
  assert.equal(roomArea(plan.rooms[0]!), 20_000_000);
  assert.deepEqual(plan.openings.map((o) => o.kind), ["door", "window"]);
  assert.deepEqual(planBounds(plan), { minX: 0, minY: 0, maxX: 4000, maxY: 5000 });
  assert.equal(wallLength(plan.walls[0]!), 4000);
});

test("a whole-house plan is the same model with several rooms", () => {
  const house = sampleHouse();
  assert.equal(house.rooms.length, 3);
  const total = house.rooms.reduce((sum, r) => sum + roomArea(r), 0);
  assert.equal(total, 80_000_000); // 10 m × 8 m
  for (const o of house.openings) assert.ok(house.walls[o.wall], "every opening sits on a real wall");
});

test("an imported plan is validated and bad openings are dropped, not fatal", () => {
  assert.equal(parseFloorPlan(null), null);
  assert.equal(parseFloorPlan({ walls: [{ a: [0, 0], b: ["x", 1] }] }), null);
  assert.equal(parseFloorPlan({ walls: [], rooms: [] }), null);
  const plan = parseFloorPlan({
    name: "P",
    walls: [{ a: [0, 0], b: [1000, 0] }],
    openings: [{ wall: 0, offset_mm: 100, width_mm: 800, kind: "window" }, { wall: 7, offset_mm: 0, width_mm: 800 }],
  });
  assert.equal(plan?.openings.length, 1);
  assert.equal(plan?.walls[0]?.thickness_mm, 120);
});

test("hit-testing finds the topmost annotation near a plan point", () => {
  const items: Annotation[] = [
    pin("a", 1, [100, 100]),
    { ...base, id: "b", kind: "rect", from: [0, 0], to: [1000, 1000] },
    { ...base, id: "c", kind: "circle", centre: [2000, 2000], radius_mm: 300 },
    { ...base, id: "d", kind: "arrow", from: [0, 3000], to: [1000, 3000] },
    { ...base, id: "e", kind: "freehand", points: [[4000, 0], [4000, 500], [4500, 500]] },
    { ...base, id: "f", kind: "text", at: [5000, 5000], text: "Hello", size_mm: 100 },
  ];
  assert.equal(hitTest(items, [105, 98], 40)?.id, "a");
  assert.equal(hitTest(items, [500, 3], 40)?.id, "b"); // rect edge
  assert.equal(hitTest(items, [500, 500], 40), null); // rect interior is not a hit
  assert.equal(hitTest(items, [2300, 2000], 40)?.id, "c"); // circle edge
  assert.equal(hitTest(items, [2000, 2000], 40), null);
  assert.equal(hitTest(items, [500, 3010], 40)?.id, "d");
  assert.equal(hitTest(items, [4200, 505], 40)?.id, "e");
  assert.equal(hitTest(items, [5100, 5050], 40)?.id, "f");
  // overlapping: the later one wins
  assert.equal(hitTest([pin("x", 1, [0, 0]), pin("y", 2, [10, 0])], [5, 0], 40)?.id, "y");
});

test("moving an annotation shifts every coordinate and leaves the original alone", () => {
  const rect: Annotation = { ...base, id: "r", kind: "rect", from: [0, 0], to: [10, 20] };
  const moved = moveAnnotation(rect, 5, -5) as typeof rect;
  assert.deepEqual([moved.from, moved.to], [[5, -5], [15, 15]]);
  assert.deepEqual([rect.from, rect.to], [[0, 0], [10, 20]]);
  const free: Annotation = { ...base, id: "f", kind: "freehand", points: [[0, 0], [1, 1]] };
  assert.deepEqual((moveAnnotation(free, 1, 1) as typeof free).points, [[1, 1], [2, 2]]);
  const circle: Annotation = { ...base, id: "c", kind: "circle", centre: [1, 1], radius_mm: 5 };
  assert.deepEqual((moveAnnotation(circle, 2, 0) as typeof circle).centre, [3, 1]);
});

test("pins are numbered from the highest existing number", () => {
  assert.equal(nextPinNumber([]), 1);
  assert.equal(nextPinNumber([pin("a", 1, [0, 0]), pin("b", 5, [1, 1])]), 6);
});

test("lengths read in mm below a metre and metres above", () => {
  assert.equal(formatLength(820), "820 mm");
  assert.equal(formatLength(3450), "3.45 m");
  assert.equal(distanceBetween([0, 0], [3, 4]), 5);
});

test("a revision cloud is a closed scalloped path of arcs", () => {
  const path = cloudPath([0, 0], [1000, 600], 200);
  assert.ok(path.startsWith("M 0 0"));
  assert.ok(path.endsWith("Z"));
  assert.equal((path.match(/A /g) ?? []).length, 5 + 3 + 5 + 3); // one arc per ~200 mm of each side
  assert.ok(cloudPath([0, 0], [0, 0], 0).includes("A")); // degenerate input still terminates
});

test("history supports undo, redo and drops redo after a new edit", () => {
  let h = newHistory<number[]>([]);
  h = commit(h, [1]);
  h = commit(h, [1, 2]);
  assert.deepEqual(undo(h).present, [1]);
  assert.deepEqual(redo(undo(h)).present, [1, 2]);
  const branched = commit(undo(h), [1, 3]);
  assert.deepEqual(branched.future, []);
  assert.equal(undo(newHistory(0)).present, 0); // nothing to undo is a no-op
  assert.equal(commit(h, h.present), h); // an unchanged state does not grow history
});

test("stored annotations survive a round trip and malformed ones are dropped", () => {
  const good: Annotation[] = [
    pin("a", 1, [1, 2]),
    { ...base, id: "t", kind: "text", at: [0, 0], text: "x", size_mm: 100 },
    { ...base, id: "d", kind: "dimension", from: [0, 0], to: [100, 0] },
  ];
  assert.deepEqual(parseAnnotations(JSON.parse(JSON.stringify(good))), good);
  const mixed = parseAnnotations([...good, { id: "bad", kind: "pin", at: ["x", 1], number: 1 }, { kind: "nope" }, null, 7]);
  assert.equal(mixed.length, 3);
  assert.deepEqual(parseAnnotations("nope"), []);
});
