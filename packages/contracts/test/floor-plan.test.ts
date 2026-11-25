/** T-237: plan geometry, annotation hit-testing/moving and undo/redo. */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  type Annotation,
  type PlanWall,
  cloudPath,
  commit,
  decimateFreehandPoints,
  distanceBetween,
  FREEHAND_POINT_LIMIT,
  floorPlanMeasurements,
  formatLength,
  hitTest,
  isClosedWallLoop,
  mergeAnnotationChanges,
  moveAnnotation,
  newHistory,
  nextPinNumber,
  openWallEndpoints,
  parseAnnotations,
  parseFloorPlan,
  planBounds,
  rectangularRoom,
  redo,
  roomArea,
  sampleHouse,
  stairPlanLines,
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

test("a measured room reports floor, ceiling, gross and legacy-safe net wall dimensions", () => {
  const plan = rectangularRoom(4000, 5000, "Studio");
  const measurements = floorPlanMeasurements(plan, 2800);
  assert.ok(measurements);
  assert.deepEqual(
    {
      floor: measurements.floor_area_m2,
      ceiling: measurements.ceiling_area_m2,
      height: measurements.ceiling_height_mm,
      width: measurements.width_mm,
      depth: measurements.depth_mm,
    },
    { floor: 20, ceiling: 20, height: 2800, width: 4000, depth: 5000 },
  );
  assert.deepEqual(measurements.rooms[0], {
    name: "Studio",
    area_m2: 20,
    width_mm: 4000,
    depth_mm: 5000,
  });
  assert.deepEqual(
    measurements.walls.map((wall) => [wall.length_mm, wall.height_mm, wall.gross_area_m2, wall.net_area_m2]),
    [
      [4000, 2800, 11.2, 11.2],
      [5000, 2800, 14, 14],
      [4000, 2800, 11.2, 11.2],
      [5000, 2800, 14, 14],
    ],
  );
  assert.equal(floorPlanMeasurements(plan, 0), null);
});

test("net wall area subtracts only measured openings and clamps bad source data to zero", () => {
  const plan = rectangularRoom(4000, 5000, "Studio");
  plan.openings = [
    { wall: 0, offset_mm: 100, width_mm: 900, height_mm: 2100, kind: "door" },
    { wall: 0, offset_mm: 1500, width_mm: 1000, kind: "window" },
    { wall: 1, offset_mm: 0, width_mm: 6000, height_mm: 3000, kind: "opening" },
  ];

  const measurements = floorPlanMeasurements(plan, 2800);
  assert.ok(measurements);
  assert.equal(measurements.walls[0]?.gross_area_m2, 11.2);
  assert.equal(measurements.walls[0]?.net_area_m2, 9.31);
  assert.equal(measurements.walls[1]?.gross_area_m2, 14);
  assert.equal(measurements.walls[1]?.net_area_m2, 0);
});

test("a semantically edited wall reports its own measured height", () => {
  const plan = rectangularRoom(4000, 5000, "Studio");
  plan.walls[1] = { ...plan.walls[1]!, height_mm: 3200, material_id: "interior.paint.sage-matte.v1" };
  const measurements = floorPlanMeasurements(plan, 2800);
  assert.ok(measurements);
  assert.equal(measurements.walls[1]?.height_mm, 3200);
  assert.equal(measurements.walls[1]?.gross_area_m2, 16);
  assert.equal(parseFloorPlan(plan)?.walls[1]?.material_id, "interior.paint.sage-matte.v1");
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
    openings: [
      { wall: 0, offset_mm: 100, width_mm: 300, height_mm: 1200, kind: "window" },
      { wall: 0, offset_mm: 500, width_mm: 300, kind: "opening" },
      { wall: 7, offset_mm: 0, width_mm: 800 },
      { wall: 0, offset_mm: 0, width_mm: 100, height_mm: -1, kind: "door" },
      { wall: 0, offset_mm: 0, width_mm: 100, height_mm: Number.NaN, kind: "door" },
      { wall: 0, offset_mm: 0, width_mm: 100, height_mm: Number.POSITIVE_INFINITY, kind: "door" },
    ],
  });
  assert.deepEqual(plan?.openings.map((opening) => opening.kind), ["window", "opening"]);
  assert.deepEqual(plan?.openings.map((opening) => opening.height_mm), [1200, undefined]);
  assert.equal(plan?.walls[0]?.thickness_mm, 120);
  const typed = parseFloorPlan({
    rooms: [{
      name: "Bedroom",
      outline: [[0, 0], [4000, 0], [4000, 4000], [0, 4000]],
      kind: "bedroom",
      requested_area_m2: [10, 20],
    }],
  });
  assert.equal(typed?.rooms[0]?.kind, "bedroom");
  assert.deepEqual(typed?.rooms[0]?.requested_area_m2, [10, 20]);
  assert.equal(parseFloorPlan({
    rooms: [{ name: "Bad", outline: [[0, 0], [1, 0], [0, 1]], kind: "garage" }],
  }), null);
});

test("a stair footprint is validated and follows plan translation", () => {
  const plan = parseFloorPlan({
    rooms: [{ name: "Floor", outline: [[0, 0], [12000, 0], [12000, 8000], [0, 8000]] }],
    stairs: [{
      id: "stair_1_2_up",
      role: "up",
      from_floor: 0,
      to_floor: 1,
      outline: [[3600, 3500], [8360, 3500], [8360, 4500], [3600, 4500]],
      width_mm: 1000,
      run_mm: 4760,
      step_count: 17,
      tread_depth_mm: 280,
      riser_height_mm: 3000 / 17,
      railing: true,
      material_id: "interior.wood.oak-natural.v1",
    }],
  });
  assert.ok(plan);
  assert.equal(plan.stairs?.[0]?.role, "up");
  assert.deepEqual(translatePlan(plan, 100, -200).stairs?.[0]?.outline[0], [3700, 3300]);
  assert.equal(parseFloorPlan({
    rooms: [{ name: "Floor", outline: [[0, 0], [1, 0], [0, 1]] }],
    stairs: [{ ...plan.stairs?.[0], step_count: 31 }],
  }), null);
  assert.equal(parseFloorPlan({
    rooms: [{ name: "Floor", outline: [[0, 0], [1, 0], [0, 1]] }],
    stairs: [{ ...plan.stairs?.[0], riser_height_mm: Number.NaN }],
  }), null);
  assert.equal(parseFloorPlan({
    rooms: [{ name: "Floor", outline: [[0, 0], [1, 0], [0, 1]] }],
    stairs: [{ ...plan.stairs?.[0], material_id: "" }],
  }), null);
});

test("an L-turn stair keeps flights and landing through parsing, drawing and translation", () => {
  const lTurn = {
    id: "stair_1_2_up",
    role: "up",
    from_floor: 0,
    to_floor: 1,
    kind: "l_turn",
    turn: "left",
    outline: [[4380, 2380], [7620, 2380], [7620, 5620], [6620, 5620], [6620, 3380], [4380, 3380]],
    flights: [
      { outline: [[4380, 2380], [6620, 2380], [6620, 3380], [4380, 3380]], step_count: 8, direction: "+x" },
      { outline: [[6620, 3380], [7620, 3380], [7620, 5620], [6620, 5620]], step_count: 8, direction: "+y" },
    ],
    landing: [[6620, 2380], [7620, 2380], [7620, 3380], [6620, 3380]],
    width_mm: 1000,
    run_mm: 4480,
    step_count: 17,
    tread_depth_mm: 280,
    riser_height_mm: 3000 / 17,
    railing: true,
  };
  const rooms = [{ name: "Floor", outline: [[0, 0], [12000, 0], [12000, 8000], [0, 8000]] }];
  const plan = parseFloorPlan({ rooms, stairs: [lTurn] });
  assert.ok(plan);
  const stair = plan.stairs![0]!;
  assert.equal(stair.kind, "l_turn");
  assert.equal(stair.flights?.length, 2);
  const lines = stairPlanLines(stair);
  assert.ok(lines);
  assert.equal(lines.treads.length, 9 + 9);
  assert.deepEqual(lines.walkline, [[4380, 2880], [7120, 2880], [7120, 5620]]);
  const down = stairPlanLines({ ...stair, role: "down" });
  assert.deepEqual(down?.walkline.at(-1), [4380, 2880]);
  const moved = translatePlan(plan, 100, -200).stairs![0]!;
  assert.deepEqual(moved.flights?.[1]?.outline[0], [6720, 3180]);
  assert.deepEqual(moved.landing?.[0], [6720, 2180]);

  for (const broken of [
    { ...lTurn, outline: lTurn.outline.slice(0, 4) },
    { ...lTurn, step_count: 18 },
    { ...lTurn, turn: "up" },
    { ...lTurn, landing: null },
    { ...lTurn, flights: [lTurn.flights[0]] },
    { ...lTurn, flights: [lTurn.flights[0], { ...lTurn.flights[1], direction: "-x" }] },
    { ...lTurn, kind: "spiral" },
  ]) {
    assert.equal(parseFloorPlan({ rooms, stairs: [broken] }), null);
  }
});

/** Exactly what the server emits for the default winder stair in a 12 × 8 m house. */
const winderLeft = {
  id: "stair_1_2_up",
  role: "up",
  from_floor: 0,
  to_floor: 1,
  kind: "winder_turn",
  turn: "left",
  outline: [[4395, 2395], [7605, 2395], [7605, 5605], [6605, 5605], [6605, 3395], [4395, 3395]],
  flights: [
    { outline: [[4395, 2395], [6355, 2395], [6355, 3395], [4395, 3395]], step_count: 7, direction: "+x" },
    { outline: [[6605, 3645], [7605, 3645], [7605, 5605], [6605, 5605]], step_count: 7, direction: "+y" },
  ],
  landing: null,
  winders: [
    [[6355, 3395], [6355, 2395], [7076.687836487032, 2395], [6499.337567297406, 3395]],
    [[6499.337567297406, 3395], [7076.687836487032, 2395], [7605, 2395], [7605, 2923.312163512968], [6605, 3500.662432702594], [6605, 3395]],
    [[6605, 3500.662432702594], [7605, 2923.312163512968], [7605, 3645], [6605, 3645]],
  ],
  newel: [[6355, 3395], [6605, 3395], [6605, 3645], [6355, 3645]],
  width_mm: 1000,
  run_mm: 3920,
  step_count: 17,
  tread_depth_mm: 280,
  riser_height_mm: 3000 / 17,
  railing: false,
};
/** The server's right turn: mirrored about the house axis, polygons still counter-clockwise. */
const winderRight = {
  ...winderLeft,
  turn: "right",
  outline: [[4395, 4605], [6605, 4605], [6605, 2395], [7605, 2395], [7605, 5605], [4395, 5605]],
  flights: [
    { outline: [[4395, 4605], [6355, 4605], [6355, 5605], [4395, 5605]], step_count: 7, direction: "+x" },
    { outline: [[6605, 2395], [7605, 2395], [7605, 4355], [6605, 4355]], step_count: 7, direction: "-y" },
  ],
  winders: [
    [[6499.337567297406, 4605], [7076.687836487032, 5605], [6355, 5605], [6355, 4605]],
    [[6605, 4605], [6605, 4499.337567297406], [7605, 5076.687836487032], [7605, 5605], [7076.687836487032, 5605], [6499.337567297406, 4605]],
    [[6605, 4355], [7605, 4355], [7605, 5076.687836487032], [6605, 4499.337567297406]],
  ],
  newel: [[6355, 4355], [6605, 4355], [6605, 4605], [6355, 4605]],
};

test("a winder stair keeps three treads and its newel through parsing, drawing and translation", () => {
  const rooms = [{ name: "Floor", outline: [[0, 0], [12000, 0], [12000, 8000], [0, 8000]] }];
  for (const [source, lowerY, sign] of [[winderLeft, 2895, 1], [winderRight, 5105, -1]] as const) {
    const plan = parseFloorPlan({ rooms, stairs: [source] });
    assert.ok(plan);
    const stair = plan.stairs![0]!;
    assert.equal(stair.kind, "winder_turn");
    assert.equal(stair.turn, source.turn);
    assert.equal(stair.winders?.length, 3);
    assert.equal(stair.landing, undefined);
    const lines = stairPlanLines(stair)!;
    // Both flights' risers plus the two inner winder risers; no tread line crosses the newel.
    assert.equal(lines.treads.length, 8 + 2 + 8);
    assert.equal(lines.walkline.length, 6);
    assert.deepEqual(lines.walkline[0], [4395, lowerY]);
    assert.deepEqual(lines.walkline[1], [6355, lowerY]);
    assert.deepEqual(lines.walkline[4], [7105, 4000 - sign * 355]);
    assert.deepEqual(lines.walkline[5], [7105, 4000 + sign * 1605]);
    const down = stairPlanLines({ ...stair, role: "down" })!;
    assert.deepEqual(down.walkline, [...lines.walkline].reverse());
    const movedPlan = translatePlan(plan, 100, -200);
    const moved = movedPlan.stairs![0]!;
    assert.deepEqual(moved.winders?.[0]?.[0], [source.winders[0]![0]![0]! + 100, source.winders[0]![0]![1]! - 200]);
    assert.deepEqual(moved.newel?.[0], [source.newel[0]![0]! + 100, source.newel[0]![1]! - 200]);
    assert.equal(stairPlanLines(moved)?.treads.length, 18);
    assert.ok(parseFloorPlan(JSON.parse(JSON.stringify(movedPlan))));
  }

  const nudged = winderLeft.winders.map((winder, index) => (
    index === 0 ? winder.map(([x, y]) => [x! + 1, y!]) : winder
  ));
  for (const broken of [
    { ...winderLeft, outline: winderLeft.outline.slice(0, 4) },
    { ...winderLeft, step_count: 18 },
    { ...winderLeft, turn: "right" },
    { ...winderLeft, turn: undefined },
    { ...winderLeft, railing: true },
    { ...winderLeft, newel: null },
    { ...winderLeft, newel: winderLeft.newel.slice(0, 3) },
    { ...winderLeft, landing: winderLeft.newel },
    { ...winderLeft, winders: undefined },
    { ...winderLeft, winders: winderLeft.winders.slice(0, 2) },
    { ...winderLeft, winders: nudged },
    { ...winderLeft, flights: [winderLeft.flights[0]] },
    { ...winderLeft, kind: "l_turn", landing: winderLeft.newel },
  ]) {
    assert.equal(parseFloorPlan({ rooms, stairs: [broken] }), null);
  }
});

test("a spiral stair keeps circular geometry through parsing, drawing and translation", () => {
  const center: [number, number] = [6_000, 4_000];
  const outline = Array.from({ length: 24 }, (_, index): [number, number] => {
    const angle = index * Math.PI / 12;
    const radius = 1_100 / Math.cos(Math.PI / 24);
    return [center[0] + radius * Math.cos(angle), center[1] + radius * Math.sin(angle)];
  });
  const source = {
    id: "stair_1_2_up",
    role: "up",
    from_floor: 0,
    to_floor: 1,
    kind: "spiral",
    turn: "right",
    outline,
    width_mm: 1_000,
    run_mm: 600 * 300 * Math.PI / 180,
    step_count: 15,
    tread_depth_mm: 600 * 20 * Math.PI / 180,
    riser_height_mm: 200,
    railing: false,
    flights: [],
    landing: null,
    winders: [],
    newel: null,
    spiral: {
      center,
      radius_mm: 1_100,
      post_radius_mm: 100,
      start_angle_deg: 0,
      sweep_deg: 300,
    },
  };
  const rooms = [{ name: "Floor", outline: [[0, 0], [12000, 0], [12000, 8000], [0, 8000]] }];
  const plan = parseFloorPlan({ rooms, stairs: [source] });
  assert.ok(plan);
  const stair = plan.stairs![0]!;
  assert.equal(stair.kind, "spiral");
  assert.deepEqual(stair.spiral?.center, center);
  const lines = stairPlanLines(stair)!;
  assert.equal(lines.treads.length, 16);
  assert.equal(lines.walkline.length, 16);
  assert.deepEqual(lines.walkline[0], [6_600, 4_000]);
  assert.ok(Math.abs(lines.walkline.at(-1)![0] - 6_300) < 1e-9);
  assert.ok(Math.abs(lines.walkline.at(-1)![1] - (4_000 + 300 * Math.sqrt(3))) < 1e-9);
  assert.deepEqual(stairPlanLines({ ...stair, role: "down" })?.walkline, [...lines.walkline].reverse());
  const moved = translatePlan(plan, 100, -200).stairs![0]!;
  assert.deepEqual(moved.spiral?.center, [6_100, 3_800]);
  assert.deepEqual(moved.outline[0], [outline[0]![0] + 100, outline[0]![1] - 200]);

  for (const broken of [
    { ...source, outline: source.outline.slice(0, 23) },
    { ...source, turn: undefined },
    { ...source, railing: true },
    { ...source, spiral: null },
    { ...source, spiral: { ...source.spiral, post_radius_mm: 1_100 } },
    { ...source, spiral: { ...source.spiral, sweep_deg: 331 } },
    { ...source, flights: [{ outline: source.outline.slice(0, 4), step_count: 5, direction: "+x" }] },
    { ...source, landing: source.outline.slice(0, 4) },
    { ...source, kind: "straight" },
  ]) {
    assert.equal(parseFloorPlan({ rooms, stairs: [broken] }), null);
  }
});

test("straight stair drawing is unchanged by the L-turn helper", () => {
  const plan = parseFloorPlan({
    rooms: [{ name: "Floor", outline: [[0, 0], [12000, 0], [12000, 8000], [0, 8000]] }],
    stairs: [{
      id: "stair_1_2_down",
      role: "down",
      from_floor: 0,
      to_floor: 1,
      outline: [[3600, 3500], [8360, 3500], [8360, 4500], [3600, 4500]],
      width_mm: 1000,
      run_mm: 4760,
      step_count: 17,
      tread_depth_mm: 280,
      riser_height_mm: 3000 / 17,
      railing: false,
    }],
  });
  const stair = plan!.stairs![0]!;
  assert.equal(stair.kind, "straight");
  const lines = stairPlanLines(stair)!;
  assert.equal(lines.treads.length, 18);
  assert.deepEqual(lines.treads[0], [[3600, 3500], [3600, 4500]]);
  assert.deepEqual(lines.walkline, [[8360, 4000], [3600, 4000]]);
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

test("freehand samples are screen-space decimated, finite and client-bounded", () => {
  const noisy: [number, number][] = [
    [0, 0],
    [1, 0],
    [Number.NaN, 4],
    [3, 0],
    [4, Number.POSITIVE_INFINITY],
    [4, 0],
  ];
  assert.deepEqual(decimateFreehandPoints(noisy, 1, 2), [[0, 0], [3, 0], [4, 0]]);

  const dense = Array.from({ length: 20 }, (_, index): [number, number] => [index, index % 2]);
  const bounded = decimateFreehandPoints(dense, 0.1, 0, 5);
  assert.equal(bounded.length, 5);
  assert.deepEqual(bounded[0], dense[0]);
  assert.deepEqual(bounded.at(-1), dense.at(-1));
  assert.deepEqual(decimateFreehandPoints([[7, 8], [7, 8]], 1), [[7, 8], [7, 8]]);

  const overClientLimit = Array.from(
    { length: FREEHAND_POINT_LIMIT + 200 },
    (_, index): [number, number] => [index, index % 3],
  );
  const hardBounded = decimateFreehandPoints(overClientLimit, 1, 0, 5_000);
  assert.equal(hardBounded.length, FREEHAND_POINT_LIMIT);
  assert.deepEqual(hardBounded[0], overClientLimit[0]);
  assert.deepEqual(hardBounded.at(-1), overClientLimit.at(-1));
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

test("annotation photos and versioned 3D anchors survive parsing safely", () => {
  const attached: Annotation = {
    ...pin("photo", 1, [10, 20]),
    photo_asset_ids: ["asset-1", "asset-2"],
    model_anchor_mm: [125.5, -42, 830],
    model_version_id: "version-1",
  };
  assert.deepEqual(parseAnnotations([attached]), [attached]);

  const malformed = parseAnnotations([
    { ...attached, model_anchor_mm: [0, Number.NaN, 0] },
    { ...attached, model_version_id: null },
    { ...attached, photo_asset_ids: ["ok", 7, ...Array.from({ length: 12 }, (_, index) => `p-${index}`)] },
  ]);
  assert.deepEqual(
    malformed.slice(0, 2).map((annotation) => [annotation.model_anchor_mm, annotation.model_version_id]),
    [[null, null], [null, null]],
  );
  assert.deepEqual(malformed[2]?.photo_asset_ids, ["ok", ...Array.from({ length: 9 }, (_, index) => `p-${index}`)]);
});

test("concurrent annotation edits merge by id without dropping independent work", () => {
  const original = pin("a", 1, [0, 0]);
  const baseAnnotations = [original];
  const local = [{ ...original, note: "local note" }, pin("local", 2, [10, 10])];
  const remote = [{ ...original, status: "resolved" as const }, pin("remote", 3, [20, 20])];
  const merged = mergeAnnotationChanges(baseAnnotations, local, remote);
  assert.deepEqual(merged.annotations.map((annotation) => annotation.id), ["a", "remote", "local"]);
  assert.equal(merged.annotations[0]?.note, "local note");
  assert.deepEqual(merged.conflicts, ["a"]);
});

test("concurrent annotation merge carries remote edits and local deletions", () => {
  const first = pin("a", 1, [0, 0]);
  const second = pin("b", 2, [10, 10]);
  const merged = mergeAnnotationChanges(
    [first, second],
    [first],
    [{ ...first, note: "remote" }, second],
  );
  assert.deepEqual(merged.annotations, [{ ...first, note: "remote" }]);
  assert.deepEqual(merged.conflicts, []);
});

import { appendRoom, mergePlans, placeBeside, translatePlan } from "../src/floor-plan.ts";

test("translating a plan moves walls and room outlines and leaves the input alone", () => {
  const room = rectangularRoom(2000, 3000);
  const moved = translatePlan(room, 500, -200);
  assert.deepEqual(planBounds(moved), { minX: 500, minY: -200, maxX: 2500, maxY: 2800 });
  assert.deepEqual(planBounds(room), { minX: 0, minY: 0, maxX: 2000, maxY: 3000 });
  assert.deepEqual(moved.openings, room.openings);
});

test("merging keeps each opening on its own wall and numbers repeated room names", () => {
  const a = rectangularRoom(3000, 3000, "Комната");
  const b = translatePlan(rectangularRoom(2000, 3000, "Комната"), 3000, 0);
  const merged = mergePlans("house", "Дом", [a, b]);
  assert.equal(merged.walls.length, 8);
  assert.equal(merged.openings.length, 4);
  for (const opening of merged.openings) assert.ok(merged.walls[opening.wall], "every opening sits on a real wall");
  // the second room's door must point at the fifth wall, not the first
  assert.equal(merged.openings[2]!.wall, a.openings[0]!.wall + 4);
  assert.deepEqual(merged.rooms.map((r) => r.name), ["Комната", "Комната 2"]);
  assert.equal(merged.rooms.reduce((sum, r) => sum + roomArea(r), 0), 9_000_000 + 6_000_000);
});

test("a new room is placed beside the plan with the top edges aligned", () => {
  const base = rectangularRoom(4000, 5000, "Гостиная");
  const next = rectangularRoom(3000, 3500, "Кухня");
  assert.deepEqual(placeBeside(base, next, 120), [4120, 0]);
  const house = appendRoom(base, next, 120);
  assert.equal(house.rooms.length, 2);
  assert.deepEqual(planBounds(house), { minX: 0, minY: 0, maxX: 7120, maxY: 5000 });
  assert.equal(house.name, "Гостиная"); // the plan keeps its name once it has a room
  // appending to an empty plan just adopts the room
  assert.equal(appendRoom({ id: "x", name: "x", walls: [], openings: [], rooms: [] }, next).rooms.length, 1);
});

test("a rectangular wall loop drawn by hand is a closed perimeter with no open ends", () => {
  const walls: PlanWall[] = rectangularRoom(4000, 3000).walls;
  assert.deepEqual(openWallEndpoints(walls), []);
  assert.equal(isClosedWallLoop(walls), true);
});

test("a dangling wall end is reported and breaks the closed-loop check", () => {
  const walls: PlanWall[] = [
    { a: [0, 0], b: [4000, 0], thickness_mm: 120 },
    { a: [4000, 0], b: [4000, 3000], thickness_mm: 120 },
    { a: [4000, 3000], b: [0, 3000], thickness_mm: 120 },
    // the loop never comes back to [0, 0]: one dangling end at each side of the gap
  ];
  const open = openWallEndpoints(walls);
  assert.equal(open.length, 2);
  assert.ok(open.some((p) => p[0] === 0 && p[1] === 0));
  assert.ok(open.some((p) => p[0] === 0 && p[1] === 3000));
  assert.equal(isClosedWallLoop(walls), false);
});

test("two walls can never close a loop, even nose to nose and back", () => {
  const walls: PlanWall[] = [
    { a: [0, 0], b: [4000, 0], thickness_mm: 120 },
    { a: [4000, 0], b: [0, 0], thickness_mm: 120 },
  ];
  assert.equal(isClosedWallLoop(walls), false);
});

test("an interior wall between two existing corners raises their degree but stays closed", () => {
  // the canvas only snaps new wall ends to existing corners (never mid-span), so an interior
  // partition is corner-to-corner — here a diagonal splitting the room into two triangles.
  const walls: PlanWall[] = [
    ...rectangularRoom(6000, 4000).walls,
    { a: [0, 0], b: [6000, 4000], thickness_mm: 100 },
  ];
  assert.equal(openWallEndpoints(walls).length, 0);
  assert.equal(isClosedWallLoop(walls), true);
});

test("a wall ending mid-span on another wall is not merged into it and reads as dangling", () => {
  // a known limitation: the loop check only merges coincident endpoints, not point-on-segment
  // T-junctions, matching the canvas which snaps new ends to corners, not to a wall's middle.
  const walls: PlanWall[] = [
    ...rectangularRoom(6000, 4000).walls,
    { a: [3000, 0], b: [3000, 4000], thickness_mm: 100 },
  ];
  assert.equal(openWallEndpoints(walls).length, 2);
  assert.equal(isClosedWallLoop(walls), false);
});

test("endpoints within epsilon of each other still merge despite float drift", () => {
  const walls: PlanWall[] = [
    { a: [0, 0], b: [4000, 0], thickness_mm: 120 },
    { a: [4000, 0], b: [4000.3, 3000], thickness_mm: 120 }, // 0.3mm off from snapping/float error
    { a: [4000, 3000], b: [0, 3000], thickness_mm: 120 },
    { a: [0.2, 3000], b: [0, 0], thickness_mm: 120 },
  ];
  assert.equal(isClosedWallLoop(walls, 1), true);
});
