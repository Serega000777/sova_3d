import type { FloorPlan, PlanRoom, PlanWall, Point } from "@physical-ai/contracts";

export type PlanEntityKind = "room" | "wall" | "node";

export interface PlanEntitySelection {
  kind: PlanEntityKind;
  index: number;
}

export function planNodes(plan: FloorPlan): Point[] {
  const nodes: Point[] = [];
  const add = (point: Point) => {
    if (!nodes.some((node) => Math.hypot(node[0] - point[0], node[1] - point[1]) <= 0.5)) {
      nodes.push(point);
    }
  };
  plan.walls.forEach((wall) => {
    add(wall.a);
    add(wall.b);
  });
  return nodes;
}

function distanceToSegment(point: Point, wall: PlanWall): number {
  const dx = wall.b[0] - wall.a[0];
  const dy = wall.b[1] - wall.a[1];
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) return Math.hypot(point[0] - wall.a[0], point[1] - wall.a[1]);
  const t = Math.max(
    0,
    Math.min(1, ((point[0] - wall.a[0]) * dx + (point[1] - wall.a[1]) * dy) / lengthSquared),
  );
  return Math.hypot(point[0] - (wall.a[0] + t * dx), point[1] - (wall.a[1] + t * dy));
}

function pointInRoom(point: Point, room: PlanRoom): boolean {
  let inside = false;
  for (let i = 0, j = room.outline.length - 1; i < room.outline.length; j = i++) {
    const a = room.outline[i] as Point;
    const b = room.outline[j] as Point;
    const crosses =
      (a[1] > point[1]) !== (b[1] > point[1]) &&
      point[0] < ((b[0] - a[0]) * (point[1] - a[1])) / (b[1] - a[1]) + a[0];
    if (crosses) inside = !inside;
  }
  return inside;
}

function planSpan(plan: FloorPlan): number {
  const points = [
    ...plan.walls.flatMap((wall) => [wall.a, wall.b]),
    ...plan.rooms.flatMap((room) => room.outline),
  ];
  if (points.length === 0) return 1;
  const xs = points.map((point) => point[0]);
  const ys = points.map((point) => point[1]);
  return Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 1);
}

/**
 * Resolve a model-space XY hit against exact plan geometry. A miss stays a miss: callers must
 * not invent a room or wall correspondence for free-form geometry.
 */
export function planEntityAtPoint(plan: FloorPlan, point: Point): PlanEntitySelection | null {
  const span = planSpan(plan);
  const nodes = planNodes(plan);
  const nodeTolerance = Math.max(60, span * 0.012);
  let closestNode = -1;
  let closestNodeDistance = Infinity;
  nodes.forEach((node, index) => {
    const distance = Math.hypot(node[0] - point[0], node[1] - point[1]);
    if (distance < closestNodeDistance) {
      closestNode = index;
      closestNodeDistance = distance;
    }
  });
  if (closestNode >= 0 && closestNodeDistance <= nodeTolerance) {
    return { kind: "node", index: closestNode };
  }

  let closestWall = -1;
  let closestWallDistance = Infinity;
  plan.walls.forEach((wall, index) => {
    const distance = distanceToSegment(point, wall);
    if (distance < closestWallDistance) {
      closestWall = index;
      closestWallDistance = distance;
    }
  });
  if (closestWall >= 0) {
    const wall = plan.walls[closestWall] as PlanWall;
    const wallTolerance = Math.max(40, wall.thickness_mm * 0.75, span * 0.008);
    if (closestWallDistance <= wallTolerance) return { kind: "wall", index: closestWall };
  }

  const room = plan.rooms.findIndex((candidate) => pointInRoom(point, candidate));
  return room >= 0 ? { kind: "room", index: room } : null;
}

export function planSelectionPoints(
  plan: FloorPlan,
  selection: PlanEntitySelection | null,
): Point[] {
  if (!selection) return [];
  if (selection.kind === "room") return plan.rooms[selection.index]?.outline ?? [];
  if (selection.kind === "wall") {
    const wall = plan.walls[selection.index];
    return wall ? [wall.a, wall.b] : [];
  }
  const node = planNodes(plan)[selection.index];
  return node ? [node] : [];
}

export function planSelectionLabel(
  plan: FloorPlan,
  selection: PlanEntitySelection | null,
): string | null {
  if (!selection) return null;
  if (selection.kind === "room") {
    const room = plan.rooms[selection.index];
    return room ? `Комната · ${room.name}` : null;
  }
  if (selection.kind === "wall") return plan.walls[selection.index] ? `Стена ${selection.index + 1}` : null;
  return planNodes(plan)[selection.index] ? `Узел ${selection.index + 1}` : null;
}

export function isValidFloorPlan(value: unknown): value is FloorPlan {
  if (!value || typeof value !== "object") return false;
  const plan = value as Partial<FloorPlan>;
  if (typeof plan.id !== "string" || typeof plan.name !== "string") return false;
  if (!Array.isArray(plan.walls) || !Array.isArray(plan.rooms) || !Array.isArray(plan.openings)) return false;
  const finitePoint = (point: unknown): point is Point =>
    Array.isArray(point) && point.length === 2 && point.every((coordinate) => Number.isFinite(coordinate));
  return (
    plan.walls.every(
      (wall) =>
        finitePoint(wall.a) && finitePoint(wall.b) && Number.isFinite(wall.thickness_mm) && wall.thickness_mm > 0,
    ) &&
    plan.rooms.every(
      (room) => typeof room.name === "string" && room.outline.length >= 3 && room.outline.every(finitePoint),
    ) &&
    plan.openings.every(
      (opening) =>
        Number.isInteger(opening.wall) &&
        opening.wall >= 0 &&
        opening.wall < (plan.walls?.length ?? 0) &&
        Number.isFinite(opening.offset_mm) &&
        Number.isFinite(opening.width_mm),
    )
  );
}
