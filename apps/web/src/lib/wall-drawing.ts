/**
 * Pure geometry for the freeform wall-drawing canvas (T-238): grid/endpoint snapping, hit
 * testing an existing wall for the erase tool, and turning a drag rectangle into four walls.
 * Kept apart from `WallDrawingCanvas.tsx` so this logic is testable without a DOM or canvas.
 */
import { type PlanWall, type Point, distanceBetween } from "@physical-ai/contracts";

export const GRID_STEP_MM = 100;
export const MIN_WALL_MM = 200;

export function snapToGrid(v: number, step = GRID_STEP_MM): number {
  return Math.round(v / step) * step;
}

/** The nearest existing wall end within `tolerance_mm`, or null — corners snap to each other. */
export function nearestEndpoint(point: Point, walls: readonly PlanWall[], tolerance_mm: number): Point | null {
  let best: Point | null = null;
  let bestDistance = tolerance_mm;
  for (const wall of walls) {
    for (const candidate of [wall.a, wall.b]) {
      const d = distanceBetween(point, candidate);
      if (d <= bestDistance) {
        best = candidate;
        bestDistance = d;
      }
    }
  }
  return best;
}

/** Snap to an existing corner first, falling back to the drawing grid. */
export function snapPoint(raw: Point, walls: readonly PlanWall[], tolerance_mm: number): Point {
  return nearestEndpoint(raw, walls, tolerance_mm) ?? [snapToGrid(raw[0]), snapToGrid(raw[1])];
}

export function distanceToSegment(p: Point, a: Point, b: Point): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const lengthSquared = dx * dx + dy * dy;
  const t = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / lengthSquared));
  return distanceBetween(p, [a[0] + dx * t, a[1] + dy * t]);
}

/** The wall whose stroke the point falls within `tolerance_mm` of, nearest first. */
export function hitWallIndex(point: Point, walls: readonly PlanWall[], tolerance_mm: number): number | null {
  let best: number | null = null;
  let bestDistance = tolerance_mm;
  walls.forEach((wall, index) => {
    const d = Math.max(0, distanceToSegment(point, wall.a, wall.b) - wall.thickness_mm / 2);
    if (d <= bestDistance) {
      best = index;
      bestDistance = d;
    }
  });
  return best;
}

/** Four walls closing the rectangle between two opposite corners. */
export function rectangleWalls(a: Point, b: Point, thickness_mm: number): PlanWall[] {
  const corners: Point[] = [a, [b[0], a[1]], b, [a[0], b[1]]];
  return corners.map((corner, i) => ({ a: corner, b: corners[(i + 1) % 4] as Point, thickness_mm }));
}
