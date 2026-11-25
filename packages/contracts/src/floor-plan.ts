/**
 * Floor plans and their markup (T-237, F-087).
 *
 * A plan is flat geometry in millimetres — one scanned room or a whole building with several
 * rooms — and an annotation lives at plan coordinates, never screen pixels, so it stays put
 * when the view pans, zooms or the plan is revised. The same model serves a single room and a
 * merged building (T-197): a building is simply a plan with more than one room.
 */

export type Point = [number, number];
export const ROOM_KINDS = [
  "bedroom",
  "kitchen_living",
  "living_room",
  "bathroom",
  "entry",
  "office",
  "nursery",
  "storage",
] as const;
export type RoomKind = (typeof ROOM_KINDS)[number];

export interface PlanWall {
  a: Point;
  b: Point;
  thickness_mm: number;
  height_mm?: number | null;
  material_id?: string | null;
}

export interface PlanOpening {
  /** Index into `walls`. */
  wall: number;
  /** Distance from the wall's `a` end to the opening's near edge, mm. */
  offset_mm: number;
  width_mm: number;
  /** Measured opening height, when the source provides one. */
  height_mm?: number;
  kind: "door" | "window" | "opening";
}

export interface PlanRoom {
  name: string;
  /** Outline in plan mm, implicitly closed. */
  outline: Point[];
  kind?: RoomKind | null;
  requested_area_m2?: [number, number] | null;
}

/** One straight flight of a turning stair; `direction` is the climbing direction in plan. */
export interface PlanStairFlight {
  outline: Point[];
  step_count: number;
  direction: "+x" | "-x" | "+y" | "-y";
}

export interface PlanStair {
  id: string;
  role: "up" | "down";
  from_floor: number;
  to_floor: number;
  /** 4 corners for a straight/U-turn stair, 6 for an L-turn or winder-turn stair. */
  outline: Point[];
  width_mm: number;
  run_mm: number;
  /** Total risers between the floors; a landing counts as one, every winder too. */
  step_count: number;
  tread_depth_mm: number;
  riser_height_mm: number;
  railing: boolean;
  material_id?: string | null;
  /** Historical plans without a kind are parsed as straight. */
  kind: "straight" | "l_turn" | "u_turn" | "winder_turn";
  turn?: "left" | "right" | null;
  flights?: PlanStairFlight[];
  landing?: Point[] | null;
  /** Winder-turn only: three polygonal treads in climbing order. */
  winders?: Point[][];
  /** Winder-turn only: the open newel square the treads wind around. */
  newel?: Point[] | null;
}

export interface FloorPlan {
  id: string;
  name: string;
  walls: PlanWall[];
  openings: PlanOpening[];
  rooms: PlanRoom[];
  stairs?: PlanStair[];
}

export interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export interface PlanRoomMeasurement {
  name: string;
  area_m2: number;
  width_mm: number;
  depth_mm: number;
}

export interface PlanWallMeasurement {
  index: number;
  length_mm: number;
  height_mm: number;
  thickness_mm: number;
  /** Full length × height, before subtracting openings. */
  gross_area_m2: number;
  /** Gross area minus only openings with a known measured height, clamped to zero. */
  net_area_m2: number;
}

export interface FloorPlanMeasurements {
  rooms: PlanRoomMeasurement[];
  walls: PlanWallMeasurement[];
  floor_area_m2: number;
  ceiling_area_m2: number;
  ceiling_height_mm: number;
  width_mm: number;
  depth_mm: number;
}

export function wallLength(wall: PlanWall): number {
  return Math.hypot(wall.b[0] - wall.a[0], wall.b[1] - wall.a[1]);
}

/** How many wall ends land within `epsilon_mm` of each plan point, after merging coincident ends. */
function endpointDegrees(walls: readonly PlanWall[], epsilon_mm: number): { point: Point; degree: number }[] {
  const nodes: { point: Point; degree: number }[] = [];
  const find = (p: Point): number => {
    for (let i = 0; i < nodes.length; i += 1) {
      const node = nodes[i] as { point: Point; degree: number };
      if (Math.hypot(node.point[0] - p[0], node.point[1] - p[1]) <= epsilon_mm) return i;
    }
    nodes.push({ point: p, degree: 0 });
    return nodes.length - 1;
  };
  for (const wall of walls) {
    (nodes[find(wall.a)] as { point: Point; degree: number }).degree += 1;
    (nodes[find(wall.b)] as { point: Point; degree: number }).degree += 1;
  }
  return nodes;
}

/**
 * Wall ends touched by only one wall — a dangling end that breaks the perimeter loop. Used to
 * flag unfinished drawing on the canvas before the design can go to detailing.
 */
export function openWallEndpoints(walls: readonly PlanWall[], epsilon_mm = 1): Point[] {
  return endpointDegrees(walls, epsilon_mm)
    .filter((node) => node.degree === 1)
    .map((node) => node.point);
}

/**
 * True once the walls form at least one closed loop with no dangling ends. A finite graph where
 * every node has degree ≥ 2 always contains a cycle, so checking for dangling ends is enough —
 * no separate cycle search is needed. A closed loop needs at least three walls (a triangle).
 */
export function isClosedWallLoop(walls: readonly PlanWall[], epsilon_mm = 1): boolean {
  return walls.length >= 3 && openWallEndpoints(walls, epsilon_mm).length === 0;
}

/** Shoelace area of a room outline in mm². */
export function roomArea(room: PlanRoom): number {
  let sum = 0;
  room.outline.forEach((p, i) => {
    const q = room.outline[(i + 1) % room.outline.length] as Point;
    sum += p[0] * q[1] - q[0] * p[1];
  });
  return Math.abs(sum) / 2;
}

/**
 * Human-facing metric schedule for a measured plan.
 *
 * Floor and ceiling areas are equal because FloorPlan is deliberately a flat plan model. A
 * client must not use this helper for a sloped/vaulted ceiling unless that surface has first
 * been represented by richer geometry. A wall's gross area is its full length × height. Its net
 * area subtracts only openings that carry a measured `height_mm`; legacy/manual openings without
 * height stay in the plan but are not guessed or subtracted. Net area is clamped to zero when bad
 * source data describes more opening area than wall area.
 */
export function floorPlanMeasurements(
  plan: FloorPlan,
  ceilingHeightMm: number,
): FloorPlanMeasurements | null {
  if (!Number.isFinite(ceilingHeightMm) || ceilingHeightMm <= 0) return null;
  const bounds = planBounds(plan);
  if (!bounds || plan.rooms.length === 0 || plan.walls.length === 0) return null;

  const rooms = plan.rooms.map((room) => {
    const roomBounds = pointsBounds(room.outline);
    return {
      name: room.name,
      area_m2: roomArea(room) / 1_000_000,
      width_mm: roomBounds ? roomBounds.maxX - roomBounds.minX : 0,
      depth_mm: roomBounds ? roomBounds.maxY - roomBounds.minY : 0,
    };
  });
  const floorAreaM2 = rooms.reduce((sum, room) => sum + room.area_m2, 0);

  return {
    rooms,
    walls: plan.walls.map((wall, index) => {
      const lengthMm = wallLength(wall);
      const wallHeightMm = wall.height_mm ?? ceilingHeightMm;
      const grossAreaMm2 = lengthMm * wallHeightMm;
      const openingAreaMm2 = plan.openings.reduce(
        (sum, opening) => opening.wall === index && opening.height_mm !== undefined
          ? sum + opening.width_mm * opening.height_mm
          : sum,
        0,
      );
      return {
        index,
        length_mm: lengthMm,
        height_mm: wallHeightMm,
        thickness_mm: wall.thickness_mm,
        gross_area_m2: grossAreaMm2 / 1_000_000,
        net_area_m2: Math.max(0, grossAreaMm2 - openingAreaMm2) / 1_000_000,
      };
    }),
    floor_area_m2: floorAreaM2,
    ceiling_area_m2: floorAreaM2,
    ceiling_height_mm: ceilingHeightMm,
    width_mm: bounds.maxX - bounds.minX,
    depth_mm: bounds.maxY - bounds.minY,
  };
}

export function planBounds(plan: FloorPlan): Bounds | null {
  const points: Point[] = [
    ...plan.walls.flatMap((w) => [w.a, w.b]),
    ...plan.rooms.flatMap((r) => r.outline),
    ...(plan.stairs ?? []).flatMap((stair) => stair.outline),
  ];
  return pointsBounds(points);
}

/** Plan drawing primitives for one stair: tread lines and a walking line ending at the arrow. */
export interface StairPlanLines {
  treads: [Point, Point][];
  walkline: Point[];
}

function flightLines(
  outline: readonly Point[],
  steps: number,
  direction: "+x" | "-x" | "+y" | "-y",
): { treads: [Point, Point][]; start: Point; end: Point } {
  const bounds = pointsBounds(outline)!;
  const alongX = direction === "+x" || direction === "-x";
  const forward = direction === "+x" || direction === "+y";
  const treads: [Point, Point][] = [];
  for (let index = 0; index <= steps; index += 1) {
    const t = index / steps;
    if (alongX) {
      const x = bounds.minX + (bounds.maxX - bounds.minX) * t;
      treads.push([[x, bounds.minY], [x, bounds.maxY]]);
    } else {
      const y = bounds.minY + (bounds.maxY - bounds.minY) * t;
      treads.push([[bounds.minX, y], [bounds.maxX, y]]);
    }
  }
  const cx = (bounds.minX + bounds.maxX) / 2;
  const cy = (bounds.minY + bounds.maxY) / 2;
  const low: Point = alongX ? [bounds.minX, cy] : [cx, bounds.minY];
  const high: Point = alongX ? [bounds.maxX, cy] : [cx, bounds.maxY];
  return { treads, start: forward ? low : high, end: forward ? high : low };
}

/** The riser edge two neighbouring winder treads share, or null when they do not share one. */
function sharedEdge(before: readonly Point[], after: readonly Point[]): [Point, Point] | null {
  const shared = before.filter(([x, y]) => after.some((point) => point[0] === x && point[1] === y));
  return shared.length === 2 ? [shared[0]!, shared[1]!] : null;
}

function winderRisers(winders: readonly (readonly Point[])[]): [[Point, Point], [Point, Point]] | null {
  if (winders.length !== 3) return null;
  const first = sharedEdge(winders[0]!, winders[1]!);
  const second = sharedEdge(winders[1]!, winders[2]!);
  return first && second ? [first, second] : null;
}

/**
 * Derive tread lines and the walking line of a straight or turning stair. The walking line
 * runs bottom→top for `up` and top→bottom for `down`, so its last point carries the arrow.
 */
export function stairPlanLines(stair: PlanStair): StairPlanLines | null {
  if (stair.kind === "winder_turn") {
    const risers = winderRisers(stair.winders ?? []);
    if (stair.flights?.length !== 2 || !risers) return null;
    const [lower, upper] = stair.flights as [PlanStairFlight, PlanStairFlight];
    const first = flightLines(lower.outline, lower.step_count, lower.direction);
    const second = flightLines(upper.outline, upper.step_count, upper.direction);
    const walkline: Point[] = [
      first.start,
      first.end,
      ...risers.map(([a, b]): Point => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]),
      second.start,
      second.end,
    ];
    return {
      treads: [...first.treads, ...risers, ...second.treads],
      walkline: stair.role === "up" ? walkline : walkline.reverse(),
    };
  }
  if (stair.kind !== "straight" && stair.flights?.length === 2 && stair.landing) {
    const [lower, upper] = stair.flights as [PlanStairFlight, PlanStairFlight];
    const first = flightLines(lower.outline, lower.step_count, lower.direction);
    const second = flightLines(upper.outline, upper.step_count, upper.direction);
    const landing = pointsBounds(stair.landing);
    if (!landing) return null;
    const pivot: Point = [(landing.minX + landing.maxX) / 2, (landing.minY + landing.maxY) / 2];
    const walkline: Point[] = [first.start, pivot, second.end];
    return {
      treads: [...first.treads, ...second.treads],
      walkline: stair.role === "up" ? walkline : walkline.reverse(),
    };
  }
  if (stair.outline.length !== 4 || !pointsBounds(stair.outline)) return null;
  const flight = flightLines(stair.outline, stair.step_count, stair.role === "up" ? "+x" : "-x");
  return { treads: flight.treads, walkline: [flight.start, flight.end] };
}

export function pointsBounds(points: readonly Point[]): Bounds | null {
  if (points.length === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of points) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  return { minX, minY, maxX, maxY };
}

/** A rectangular room with four walls, a door on the south wall and a window on the north. */
export function rectangularRoom(width_mm: number, depth_mm: number, name = "Room"): FloorPlan {
  const w = Math.max(width_mm, 500);
  const d = Math.max(depth_mm, 500);
  const corners: Point[] = [[0, 0], [w, 0], [w, d], [0, d]];
  return {
    id: `room-${Math.round(w)}x${Math.round(d)}`,
    name,
    walls: corners.map((a, i) => ({ a, b: corners[(i + 1) % 4] as Point, thickness_mm: 120 })),
    openings: [
      { wall: 0, offset_mm: Math.max(w / 2 - 450, 100), width_mm: Math.min(900, w - 200), kind: "door" },
      { wall: 2, offset_mm: Math.max(w / 2 - 600, 100), width_mm: Math.min(1200, w - 200), kind: "window" },
    ],
    rooms: [{ name, outline: corners }],
  };
}

/** A house footprint split into a living room, a kitchen and a bedroom — the building-level demo. */
export function sampleHouse(): FloorPlan {
  const outer: Point[] = [[0, 0], [10000, 0], [10000, 8000], [0, 8000]];
  const wall = (a: Point, b: Point, thickness_mm = 120): PlanWall => ({ a, b, thickness_mm });
  return {
    id: "sample-house",
    name: "Дом 10 × 8 м",
    walls: [
      ...outer.map((a, i) => wall(a, outer[(i + 1) % 4] as Point, 250)),
      wall([6000, 0], [6000, 8000]),
      wall([6000, 4500], [10000, 4500]),
    ],
    openings: [
      { wall: 0, offset_mm: 2200, width_mm: 1000, kind: "door" },
      { wall: 2, offset_mm: 1500, width_mm: 1500, kind: "window" },
      { wall: 2, offset_mm: 6500, width_mm: 1500, kind: "window" },
      { wall: 4, offset_mm: 3000, width_mm: 900, kind: "door" },
      { wall: 5, offset_mm: 1200, width_mm: 900, kind: "door" },
    ],
    rooms: [
      { name: "Гостиная", outline: [[0, 0], [6000, 0], [6000, 8000], [0, 8000]] },
      { name: "Кухня", outline: [[6000, 0], [10000, 0], [10000, 4500], [6000, 4500]] },
      { name: "Спальня", outline: [[6000, 4500], [10000, 4500], [10000, 8000], [6000, 8000]] },
    ],
  };
}

/** Reads a plan from untrusted JSON, rejecting anything that would break rendering. */
export function parseFloorPlan(value: unknown): FloorPlan | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const isPoint = (p: unknown): p is Point =>
    Array.isArray(p) && p.length === 2 && p.every((n) => typeof n === "number" && Number.isFinite(n));
  const walls = Array.isArray(raw.walls) ? raw.walls : [];
  const cleanWalls: PlanWall[] = [];
  for (const w of walls) {
    const wall = w as Record<string, unknown>;
    if (!isPoint(wall?.a) || !isPoint(wall?.b)) return null;
    const thickness = typeof wall.thickness_mm === "number" && wall.thickness_mm > 0 ? wall.thickness_mm : 120;
    const height = wall.height_mm;
    const material = wall.material_id;
    if (height != null && (typeof height !== "number" || !Number.isFinite(height) || height < 500 || height > 12_000)) return null;
    if (material != null && (typeof material !== "string" || !/^[a-z0-9_.-]{1,120}$/.test(material))) return null;
    cleanWalls.push({
      a: wall.a,
      b: wall.b,
      thickness_mm: thickness,
      ...(typeof height === "number" ? { height_mm: height } : {}),
      ...(typeof material === "string" ? { material_id: material } : {}),
    });
  }
  const rooms: PlanRoom[] = [];
  for (const r of Array.isArray(raw.rooms) ? raw.rooms : []) {
    const room = r as Record<string, unknown>;
    if (!Array.isArray(room?.outline) || room.outline.length < 3 || !room.outline.every(isPoint)) return null;
    const kind = room.kind == null
      ? null
      : typeof room.kind === "string" && ROOM_KINDS.includes(room.kind as RoomKind)
        ? room.kind as RoomKind
        : undefined;
    if (room.kind != null && kind === undefined) return null;
    let requestedArea: [number, number] | null = null;
    if (room.requested_area_m2 != null) {
      if (
        !Array.isArray(room.requested_area_m2)
        || room.requested_area_m2.length !== 2
        || !room.requested_area_m2.every((value) => typeof value === "number" && Number.isFinite(value))
        || room.requested_area_m2[0] < 2
        || room.requested_area_m2[1] < room.requested_area_m2[0]
        || room.requested_area_m2[1] > 200
      ) return null;
      requestedArea = room.requested_area_m2 as [number, number];
    }
    rooms.push({
      name: typeof room.name === "string" ? room.name : "Room",
      outline: room.outline as Point[],
      ...(kind ? { kind } : {}),
      ...(requestedArea ? { requested_area_m2: requestedArea } : {}),
    });
  }
  const openings: PlanOpening[] = [];
  for (const o of Array.isArray(raw.openings) ? raw.openings : []) {
    const opening = o as Record<string, unknown>;
    const height = opening.height_mm;
    if (
      typeof opening?.wall !== "number" ||
      !Number.isInteger(opening.wall) ||
      opening.wall < 0 ||
      opening.wall >= cleanWalls.length ||
      typeof opening.offset_mm !== "number" ||
      typeof opening.width_mm !== "number" ||
      opening.width_mm <= 0 ||
      (height != null && (
        typeof height !== "number" ||
        !Number.isFinite(height) ||
        height <= 0
      ))
    ) {
      continue; // an opening on a missing wall is dropped, not fatal
    }
    openings.push({
      wall: opening.wall,
      offset_mm: opening.offset_mm,
      width_mm: opening.width_mm,
      ...(typeof height === "number" ? { height_mm: height } : {}),
      kind: opening.kind === "window" || opening.kind === "opening" ? opening.kind : "door",
    });
  }
  const stairs: PlanStair[] = [];
  for (const value of Array.isArray(raw.stairs) ? raw.stairs : []) {
    const stair = value as Record<string, unknown>;
    if (
      typeof stair.id !== "string"
      || !/^[a-z][a-z0-9_]{0,63}$/.test(stair.id)
      || (stair.role !== "up" && stair.role !== "down")
      || typeof stair.from_floor !== "number"
      || !Number.isInteger(stair.from_floor)
      || stair.from_floor < 0
      || stair.from_floor > 2
      || typeof stair.to_floor !== "number"
      || !Number.isInteger(stair.to_floor)
      || stair.to_floor < 1
      || stair.to_floor > 2
      || stair.from_floor >= stair.to_floor
      || (stair.kind != null && stair.kind !== "straight" && stair.kind !== "l_turn" && stair.kind !== "u_turn" && stair.kind !== "winder_turn")
      || !Array.isArray(stair.outline)
      || stair.outline.length !== (stair.kind === "l_turn" || stair.kind === "winder_turn" ? 6 : 4)
      || !stair.outline.every(isPoint)
      || typeof stair.width_mm !== "number"
      || !Number.isFinite(stair.width_mm)
      || stair.width_mm < 700
      || stair.width_mm > 2_000
      || typeof stair.run_mm !== "number"
      || !Number.isFinite(stair.run_mm)
      || stair.run_mm <= 0
      || stair.run_mm > 12_000
      || typeof stair.step_count !== "number"
      || !Number.isInteger(stair.step_count)
      || stair.step_count < 10
      || stair.step_count > 30
      || typeof stair.tread_depth_mm !== "number"
      || !Number.isFinite(stair.tread_depth_mm)
      || stair.tread_depth_mm < 200
      || stair.tread_depth_mm > 400
      || typeof stair.riser_height_mm !== "number"
      || !Number.isFinite(stair.riser_height_mm)
      || stair.riser_height_mm < 120
      || stair.riser_height_mm > 220
      || typeof stair.railing !== "boolean"
      || (stair.material_id != null && (
        typeof stair.material_id !== "string"
        || stair.material_id.length < 1
        || stair.material_id.length > 120
      ))
    ) return null;
    let turning: Pick<PlanStair, "kind" | "turn" | "flights" | "landing" | "winders" | "newel"> | null = null;
    const winderTurn = stair.kind === "winder_turn";
    // Winder geometry on any other kind (or a landing on a winder stair) is contradictory data.
    if (!winderTurn && (
      (stair.winders != null && !(Array.isArray(stair.winders) && stair.winders.length === 0))
      || stair.newel != null
    )) return null;
    if (stair.kind === "l_turn" || stair.kind === "u_turn" || stair.kind === "winder_turn") {
      const flights = Array.isArray(stair.flights) ? stair.flights as Record<string, unknown>[] : [];
      if (
        (stair.turn !== "left" && stair.turn !== "right")
        || (winderTurn
          ? stair.landing != null
          : !Array.isArray(stair.landing) || stair.landing.length !== 4 || !stair.landing.every(isPoint))
        || flights.length !== 2
        || !flights.every((flight) => (
          flight !== null
          && typeof flight === "object"
          && Array.isArray(flight.outline)
          && flight.outline.length === 4
          && flight.outline.every(isPoint)
          && typeof flight.step_count === "number"
          && Number.isInteger(flight.step_count)
          && flight.step_count >= 3
          && flight.step_count <= 26
          && (flight.direction === "+x" || flight.direction === "-x" || flight.direction === "+y" || flight.direction === "-y")
        ))
        || (flights[0]!.step_count as number) + (flights[1]!.step_count as number) + (winderTurn ? 3 : 1) !== stair.step_count
        || (stair.kind === "l_turn" && (
          flights[0]!.direction !== "+x"
          || (flights[1]!.direction !== "+y" && flights[1]!.direction !== "-y")
        ))
        || (stair.kind === "u_turn" && (
          flights[0]!.step_count !== flights[1]!.step_count
          || flights[0]!.direction !== "+x"
          || flights[1]!.direction !== "-x"
        ))
        || (winderTurn && (
          flights[0]!.direction !== "+x"
          || flights[1]!.direction !== (stair.turn === "left" ? "+y" : "-y")
          || stair.railing
          || !Array.isArray(stair.newel)
          || stair.newel.length !== 4
          || !stair.newel.every(isPoint)
          || !Array.isArray(stair.winders)
          || stair.winders.length !== 3
          || !stair.winders.every((winder, index) => (
            Array.isArray(winder) && winder.length === (index === 1 ? 6 : 4) && winder.every(isPoint)
          ))
          || !winderRisers(stair.winders as Point[][])
        ))
      ) return null;
      turning = {
        kind: stair.kind,
        turn: stair.turn,
        flights: flights.map((flight) => ({
          outline: flight.outline as Point[],
          step_count: flight.step_count as number,
          direction: flight.direction as PlanStairFlight["direction"],
        })),
        ...(winderTurn
          ? { winders: stair.winders as Point[][], newel: stair.newel as Point[] }
          : { landing: stair.landing as Point[] }),
      };
    }
    stairs.push({
      id: stair.id,
      role: stair.role,
      from_floor: stair.from_floor as number,
      to_floor: stair.to_floor as number,
      outline: stair.outline as Point[],
      width_mm: stair.width_mm,
      run_mm: stair.run_mm,
      step_count: stair.step_count,
      tread_depth_mm: stair.tread_depth_mm,
      riser_height_mm: stair.riser_height_mm,
      railing: stair.railing,
      material_id: stair.material_id as string | null | undefined,
      ...(turning ?? { kind: "straight" }),
    });
  }
  if (cleanWalls.length === 0 && rooms.length === 0) return null;
  return {
    id: typeof raw.id === "string" && raw.id ? raw.id : "imported-plan",
    name: typeof raw.name === "string" && raw.name ? raw.name : "Imported plan",
    walls: cleanWalls,
    openings,
    rooms,
    stairs,
  };
}

// ---------------------------------------------------------------------------------------
// Annotations
// ---------------------------------------------------------------------------------------

export type AnnotationKind =
  | "pin"
  | "cloud"
  | "rect"
  | "circle"
  | "arrow"
  | "freehand"
  | "text"
  | "dimension";

export type AnnotationStatus = "open" | "resolved";

export interface AnnotationBase {
  id: string;
  author: string;
  /** ISO timestamp. */
  created_at: string;
  status: AnnotationStatus;
  note: string;
  colour: string;
  /** Workspace-owned JPEG/PNG assets attached to this remark. */
  photo_asset_ids?: string[];
  /** Surface point chosen in the 3D Studio, in that version's model millimetres. */
  model_anchor_mm?: [number, number, number] | null;
  model_version_id?: string | null;
}

export type Annotation = AnnotationBase &
  (
    | { kind: "pin"; at: Point; number: number }
    | { kind: "cloud" | "rect"; from: Point; to: Point }
    | { kind: "circle"; centre: Point; radius_mm: number }
    | { kind: "arrow" | "dimension"; from: Point; to: Point }
    | { kind: "freehand"; points: Point[] }
    | { kind: "text"; at: Point; text: string; size_mm: number }
  );

export const ANNOTATION_COLOURS = ["#ff4d4f", "#ffb020", "#52d273", "#5b9cff", "#b37bff", "#ffffff"] as const;

export function distanceBetween(a: Point, b: Point): number {
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

/**
 * Client-side ceiling for one freehand stroke. The API deliberately allows more (5000), so a
 * client can append the release point without ever relying on server rejection as flow control.
 */
export const FREEHAND_POINT_LIMIT = 800;

/**
 * Remove touch/pointer samples that are closer than a screen-space threshold while preserving
 * the first and final finite points. `millimetresPerPixel` is the current inverse view scale,
 * which keeps the stroke density stable at every zoom level. Invalid coordinates are dropped and
 * the result is evenly thinned when it would exceed the client ceiling.
 */
export function decimateFreehandPoints(
  points: readonly Point[],
  millimetresPerPixel: number,
  minDistancePx = 2,
  maxPoints = FREEHAND_POINT_LIMIT,
): Point[] {
  const finite = points.filter(
    (point): point is Point =>
      Array.isArray(point) &&
      point.length === 2 &&
      point.every((coordinate) => Number.isFinite(coordinate)),
  );
  if (finite.length <= 1) return finite.map((point) => [...point] as Point);

  const safeMmPerPixel = Number.isFinite(millimetresPerPixel) && millimetresPerPixel > 0
    ? millimetresPerPixel
    : 0;
  const safeDistancePx = Number.isFinite(minDistancePx) && minDistancePx >= 0
    ? minDistancePx
    : 0;
  const minimumDistance = safeMmPerPixel * safeDistancePx;
  const decimated: Point[] = [[...finite[0]!] as Point];
  for (let index = 1; index < finite.length - 1; index += 1) {
    const point = finite[index]!;
    if (distanceBetween(decimated[decimated.length - 1]!, point) >= minimumDistance) {
      decimated.push([...point] as Point);
    }
  }
  const last = finite[finite.length - 1]!;
  decimated.push([...last] as Point);

  const requestedLimit = Number.isFinite(maxPoints) ? Math.max(2, Math.floor(maxPoints)) : FREEHAND_POINT_LIMIT;
  const limit = Math.min(FREEHAND_POINT_LIMIT, requestedLimit);
  if (decimated.length <= limit) return decimated;
  return Array.from({ length: limit }, (_, index) => {
    const sourceIndex = index === limit - 1
      ? decimated.length - 1
      : Math.floor((index * (decimated.length - 1)) / (limit - 1));
    return [...decimated[sourceIndex]!] as Point;
  });
}

export function nextPinNumber(annotations: readonly Annotation[]): number {
  let highest = 0;
  for (const a of annotations) if (a.kind === "pin") highest = Math.max(highest, a.number);
  return highest + 1;
}

export function annotationBounds(a: Annotation): Bounds {
  switch (a.kind) {
    case "pin":
      return { minX: a.at[0], minY: a.at[1], maxX: a.at[0], maxY: a.at[1] };
    case "text":
      return {
        minX: a.at[0],
        minY: a.at[1],
        maxX: a.at[0] + a.text.length * a.size_mm * 0.6,
        maxY: a.at[1] + a.size_mm,
      };
    case "circle":
      return {
        minX: a.centre[0] - a.radius_mm,
        minY: a.centre[1] - a.radius_mm,
        maxX: a.centre[0] + a.radius_mm,
        maxY: a.centre[1] + a.radius_mm,
      };
    case "freehand":
      return pointsBounds(a.points) ?? { minX: 0, minY: 0, maxX: 0, maxY: 0 };
    default:
      return pointsBounds([a.from, a.to]) as Bounds;
  }
}

function distanceToSegment(p: Point, a: Point, b: Point): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const lengthSquared = dx * dx + dy * dy;
  const t = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / lengthSquared));
  return distanceBetween(p, [a[0] + dx * t, a[1] + dy * t]);
}

/**
 * The topmost annotation within `tolerance_mm` of a plan point, or null. Later annotations
 * draw on top, so they win. Outlines hit near their edge; resolved annotations still hit.
 */
export function hitTest(annotations: readonly Annotation[], point: Point, tolerance_mm: number): Annotation | null {
  for (let i = annotations.length - 1; i >= 0; i -= 1) {
    const a = annotations[i] as Annotation;
    let hit = false;
    switch (a.kind) {
      case "pin":
        hit = distanceBetween(point, a.at) <= tolerance_mm * 1.5;
        break;
      case "arrow":
      case "dimension":
        hit = distanceToSegment(point, a.from, a.to) <= tolerance_mm;
        break;
      case "circle":
        hit = Math.abs(distanceBetween(point, a.centre) - a.radius_mm) <= tolerance_mm;
        break;
      case "rect":
      case "cloud": {
        const b = annotationBounds(a);
        const inside = point[0] >= b.minX - tolerance_mm && point[0] <= b.maxX + tolerance_mm && point[1] >= b.minY - tolerance_mm && point[1] <= b.maxY + tolerance_mm;
        const deep = point[0] > b.minX + tolerance_mm && point[0] < b.maxX - tolerance_mm && point[1] > b.minY + tolerance_mm && point[1] < b.maxY - tolerance_mm;
        hit = inside && !deep;
        break;
      }
      case "freehand":
        hit = a.points.some((q, j) => j > 0 && distanceToSegment(point, a.points[j - 1] as Point, q) <= tolerance_mm);
        break;
      case "text": {
        const b = annotationBounds(a);
        hit = point[0] >= b.minX - tolerance_mm && point[0] <= b.maxX + tolerance_mm && point[1] >= b.minY - tolerance_mm && point[1] <= b.maxY + tolerance_mm;
        break;
      }
    }
    if (hit) return a;
  }
  return null;
}

/** Move an annotation by a plan-space offset. Never mutates its input. */
export function moveAnnotation(a: Annotation, dx: number, dy: number): Annotation {
  const shift = (p: Point): Point => [p[0] + dx, p[1] + dy];
  switch (a.kind) {
    case "pin":
    case "text":
      return { ...a, at: shift(a.at) };
    case "circle":
      return { ...a, centre: shift(a.centre) };
    case "freehand":
      return { ...a, points: a.points.map(shift) };
    default:
      return { ...a, from: shift(a.from), to: shift(a.to) };
  }
}

/** The number a dimension annotation shows, as "3.45 m" or "820 mm". */
export function formatLength(mm: number): string {
  return Math.abs(mm) >= 1000 ? `${(mm / 1000).toFixed(2)} m` : `${Math.round(mm)} mm`;
}

/**
 * The scalloped outline of a revision cloud around a rectangle: arcs bulging outward, about
 * `bump_mm` across. Returned as SVG path data in plan mm.
 */
export function cloudPath(from: Point, to: Point, bump_mm: number): string {
  const x0 = Math.min(from[0], to[0]);
  const x1 = Math.max(from[0], to[0]);
  const y0 = Math.min(from[1], to[1]);
  const y1 = Math.max(from[1], to[1]);
  const bump = Math.max(bump_mm, 1);
  const sides: [Point, Point][] = [
    [[x0, y0], [x1, y0]],
    [[x1, y0], [x1, y1]],
    [[x1, y1], [x0, y1]],
    [[x0, y1], [x0, y0]],
  ];
  const parts: string[] = [`M ${x0} ${y0}`];
  for (const [a, b] of sides) {
    const length = distanceBetween(a, b);
    const count = Math.max(Math.round(length / bump), 1);
    const r = length / count / 2;
    for (let i = 1; i <= count; i += 1) {
      const px = a[0] + ((b[0] - a[0]) * i) / count;
      const py = a[1] + ((b[1] - a[1]) * i) / count;
      parts.push(`A ${r} ${r} 0 0 1 ${px} ${py}`);
    }
  }
  return `${parts.join(" ")} Z`;
}

// ---------------------------------------------------------------------------------------
// Undo / redo
// ---------------------------------------------------------------------------------------

export interface History<T> {
  past: T[];
  present: T;
  future: T[];
}

export const HISTORY_LIMIT = 100;

export function newHistory<T>(present: T): History<T> {
  return { past: [], present, future: [] };
}

export function commit<T>(history: History<T>, next: T): History<T> {
  if (Object.is(next, history.present)) return history;
  return { past: [...history.past, history.present].slice(-HISTORY_LIMIT), present: next, future: [] };
}

export function undo<T>(history: History<T>): History<T> {
  const previous = history.past[history.past.length - 1];
  if (previous === undefined) return history;
  return { past: history.past.slice(0, -1), present: previous, future: [history.present, ...history.future] };
}

export function redo<T>(history: History<T>): History<T> {
  const [next, ...rest] = history.future;
  if (next === undefined) return history;
  return { past: [...history.past, history.present], present: next, future: rest };
}

const KINDS: readonly AnnotationKind[] = ["pin", "cloud", "rect", "circle", "arrow", "freehand", "text", "dimension"];

/** Reads stored annotations back, dropping any entry that is malformed rather than failing the plan. */
export function parseAnnotations(value: unknown): Annotation[] {
  if (!Array.isArray(value)) return [];
  const isPoint = (p: unknown): p is Point =>
    Array.isArray(p) && p.length === 2 && p.every((n) => typeof n === "number" && Number.isFinite(n));
  const out: Annotation[] = [];
  for (const item of value) {
    const a = item as Record<string, unknown>;
    if (!a || typeof a.id !== "string" || !KINDS.includes(a.kind as AnnotationKind)) continue;
    const modelAnchor =
      Array.isArray(a.model_anchor_mm) &&
      a.model_anchor_mm.length === 3 &&
      a.model_anchor_mm.every(
        (value) => typeof value === "number" && Number.isFinite(value) && Math.abs(value) <= 1_000_000,
      ) &&
      typeof a.model_version_id === "string"
        ? (a.model_anchor_mm as [number, number, number])
        : null;
    const base = {
      id: a.id,
      author: typeof a.author === "string" ? a.author : "",
      created_at: typeof a.created_at === "string" ? a.created_at : new Date(0).toISOString(),
      status: a.status === "resolved" ? ("resolved" as const) : ("open" as const),
      note: typeof a.note === "string" ? a.note : "",
      colour: typeof a.colour === "string" ? a.colour : ANNOTATION_COLOURS[0],
      ...(Array.isArray(a.photo_asset_ids) ? {
        photo_asset_ids: a.photo_asset_ids
          .filter((id): id is string => typeof id === "string")
          .slice(0, 10),
      } : {}),
      ...(modelAnchor ? {
        model_anchor_mm: modelAnchor,
        model_version_id: a.model_version_id as string,
      } : a.model_anchor_mm !== undefined || a.model_version_id !== undefined ? {
        model_anchor_mm: null,
        model_version_id: null,
      } : {}),
    };
    switch (a.kind) {
      case "pin":
        if (isPoint(a.at) && typeof a.number === "number") out.push({ ...base, kind: "pin", at: a.at, number: a.number });
        break;
      case "text":
        if (isPoint(a.at) && typeof a.text === "string" && typeof a.size_mm === "number" && a.size_mm > 0) {
          out.push({ ...base, kind: "text", at: a.at, text: a.text, size_mm: a.size_mm });
        }
        break;
      case "circle":
        if (isPoint(a.centre) && typeof a.radius_mm === "number" && a.radius_mm > 0) {
          out.push({ ...base, kind: "circle", centre: a.centre, radius_mm: a.radius_mm });
        }
        break;
      case "freehand":
        if (Array.isArray(a.points) && a.points.length >= 2 && a.points.every(isPoint)) {
          out.push({ ...base, kind: "freehand", points: a.points as Point[] });
        }
        break;
      default:
        if (isPoint(a.from) && isPoint(a.to)) {
          out.push({ ...base, kind: a.kind as "cloud" | "rect" | "arrow" | "dimension", from: a.from, to: a.to });
        }
    }
  }
  return out;
}

export interface AnnotationMergeResult {
  annotations: Annotation[];
  /** IDs changed incompatibly on both sides. The local value wins, but the conflict is visible. */
  conflicts: string[];
}

function sameAnnotation(left: Annotation | undefined, right: Annotation | undefined): boolean {
  return left === right || JSON.stringify(left) === JSON.stringify(right);
}

/**
 * Three-way merge for a revision conflict. Independent annotations are preserved from both
 * editors. If both changed the same annotation, the local value wins and its id is reported so
 * the UI never hides that judgment. Deletions are changes too (``undefined`` is a valid side).
 */
export function mergeAnnotationChanges(
  base: readonly Annotation[],
  local: readonly Annotation[],
  remote: readonly Annotation[],
): AnnotationMergeResult {
  const baseById = new Map(base.map((annotation) => [annotation.id, annotation]));
  const localById = new Map(local.map((annotation) => [annotation.id, annotation]));
  const remoteById = new Map(remote.map((annotation) => [annotation.id, annotation]));
  const ids = [
    ...remote.map((annotation) => annotation.id),
    ...local.map((annotation) => annotation.id).filter((id) => !remoteById.has(id)),
    ...base.map((annotation) => annotation.id).filter(
      (id) => !remoteById.has(id) && !localById.has(id),
    ),
  ];
  const annotations: Annotation[] = [];
  const conflicts: string[] = [];
  for (const id of [...new Set(ids)]) {
    const ancestor = baseById.get(id);
    const ours = localById.get(id);
    const theirs = remoteById.get(id);
    let merged: Annotation | undefined;
    if (sameAnnotation(ours, ancestor)) merged = theirs;
    else if (sameAnnotation(theirs, ancestor) || sameAnnotation(ours, theirs)) merged = ours;
    else {
      merged = ours;
      conflicts.push(id);
    }
    if (merged !== undefined) annotations.push(merged);
  }
  return { annotations, conflicts };
}

// ---------------------------------------------------------------------------------------
// Merging rooms into one plan (T-197 groundwork)
// ---------------------------------------------------------------------------------------

/** A copy of the plan moved by (dx, dy) mm. Annotations are not part of a plan and stay put. */
export function translatePlan(plan: FloorPlan, dx: number, dy: number): FloorPlan {
  const move = (p: Point): Point => [p[0] + dx, p[1] + dy];
  return {
    ...plan,
    walls: plan.walls.map((wall) => ({ ...wall, a: move(wall.a), b: move(wall.b) })),
    openings: plan.openings.map((opening) => ({ ...opening })),
    rooms: plan.rooms.map((room) => ({ ...room, outline: room.outline.map(move) })),
    stairs: (plan.stairs ?? []).map((stair) => ({
      ...stair,
      outline: stair.outline.map(move),
      ...(stair.flights
        ? { flights: stair.flights.map((flight) => ({ ...flight, outline: flight.outline.map(move) })) }
        : {}),
      ...(stair.landing ? { landing: stair.landing.map(move) } : {}),
      ...(stair.winders ? { winders: stair.winders.map((winder) => winder.map(move)) } : {}),
      ...(stair.newel ? { newel: stair.newel.map(move) } : {}),
    })),
  };
}

/**
 * Several plans as one: walls and rooms are concatenated and every opening is re-pointed at its
 * wall's new index. Room names that repeat get a number so the list stays unambiguous.
 */
export function mergePlans(id: string, name: string, parts: readonly FloorPlan[]): FloorPlan {
  const walls: PlanWall[] = [];
  const openings: PlanOpening[] = [];
  const rooms: PlanRoom[] = [];
  const stairs: PlanStair[] = [];
  const seen = new Map<string, number>();
  for (const part of parts) {
    const base = walls.length;
    walls.push(...part.walls.map((wall) => ({ ...wall })));
    for (const opening of part.openings) openings.push({ ...opening, wall: opening.wall + base });
    for (const room of part.rooms) {
      const count = (seen.get(room.name) ?? 0) + 1;
      seen.set(room.name, count);
      rooms.push({ ...room, name: count === 1 ? room.name : `${room.name} ${count}` });
    }
    stairs.push(...(part.stairs ?? []).map((stair) => ({ ...stair })));
  }
  return { id, name, walls, openings, rooms, stairs };
}

/**
 * Where to put `addition` so it sits to the right of `base`, with a wall's thickness of air
 * between them, top edges aligned. Returns the offset to translate the addition by.
 */
export function placeBeside(base: FloorPlan, addition: FloorPlan, gap_mm = 0): Point {
  const a = planBounds(base);
  const b = planBounds(addition);
  if (!a || !b) return [0, 0];
  return [a.maxX + gap_mm - b.minX, a.minY - b.minY];
}

/** The plan with the numbered rooms: the first of a repeated name stays, later ones count up. */
export function appendRoom(plan: FloorPlan, room: FloorPlan, gap_mm = 0): FloorPlan {
  const [dx, dy] = placeBeside(plan, room, gap_mm);
  const moved = translatePlan(room, dx, dy);
  const merged = mergePlans(plan.id, plan.name, [plan, moved]);
  return { ...merged, name: plan.rooms.length > 0 ? plan.name : room.name };
}
