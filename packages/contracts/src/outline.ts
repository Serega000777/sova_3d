/**
 * From a drawn path to a region (T-105 / T-109, F-062 / F-034).
 *
 * Both clients project what the hand draws onto the model's surface and end up with a list
 * of points in model millimetres. This module turns that list into the region the API
 * understands, with the same rules everywhere: a straight drag while editing is a rubber-
 * band rectangle, a sweep while painting is a brush band, and a loop is filled.
 */
import type { LassoRegion, RegionSelection } from "./client.js";
import type { Axis } from "./operation-plan.js";

export type Point2 = [number, number];
export type Sign = "+" | "-";

/** The API refuses longer outlines; a hand never needs more. */
export const MAX_OUTLINE_POINTS = 256;

export const AXES: readonly Axis[] = ["x", "y", "z"];

export interface Surface {
  /** The axis the surface faces. */
  axis: Axis;
  sign: Sign;
  /** Where along that axis the surface lies, in mm. */
  offset_mm: number;
}

/** The axis a surface normal mostly points along, and which way. */
export function dominantAxis(normal: { x: number; y: number; z: number }): {
  axis: Axis;
  sign: Sign;
} {
  const components: [Axis, number][] = [
    ["x", normal.x],
    ["y", normal.y],
    ["z", normal.z],
  ];
  const [axis, value] = components.reduce((best, current) =>
    Math.abs(current[1]) > Math.abs(best[1]) ? current : best,
  );
  return { axis, sign: value >= 0 ? "+" : "-" };
}

/** The two axes an outline on `axis`'s surface lives in, in x,y,z order. */
export function planeAxes(axis: Axis): [Axis, Axis] {
  return AXES.filter((candidate) => candidate !== axis) as [Axis, Axis];
}

export function distance(a: Point2, b: Point2): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

/** Drop samples closer than `step` to the one kept before them (pointer jitter). */
export function thin(path: Point2[], step: number): Point2[] {
  const kept: Point2[] = [path[0]];
  for (const point of path.slice(1)) {
    if (distance(point, kept[kept.length - 1]) >= step) kept.push(point);
  }
  const last = path[path.length - 1];
  const tail = kept[kept.length - 1];
  if (kept.length > 1 && tail !== last && distance(last, tail) > 0) kept.push(last);
  return kept;
}

/** Every sample lies close to the chord from first to last: the hand drew a line. */
export function isStraight(path: Point2[]): boolean {
  const first = path[0];
  const last = path[path.length - 1];
  const length = distance(first, last);
  if (length < 0.5) return false;
  const tolerance = Math.max(0.5, 0.06 * length);
  const [dx, dy] = [(last[0] - first[0]) / length, (last[1] - first[1]) / length];
  return path.every(
    (p) => Math.abs((p[0] - first[0]) * dy - (p[1] - first[1]) * dx) <= tolerance,
  );
}

/** The path ends where it began: an outline to fill rather than a sweep. */
export function isClosed(path: Point2[]): boolean {
  if (path.length < 8) return false;
  const xs = path.map((p) => p[0]);
  const ys = path.map((p) => p[1]);
  const diagonal = Math.hypot(
    Math.max(...xs) - Math.min(...xs),
    Math.max(...ys) - Math.min(...ys),
  );
  return distance(path[0], path[path.length - 1]) < 0.2 * diagonal;
}

/** The axis-aligned rectangle spanning the path. */
export function rectangle(path: Point2[]): Point2[] {
  const xs = path.map((p) => p[0]);
  const ys = path.map((p) => p[1]);
  const [minX, maxX] = [Math.min(...xs), Math.max(...xs)];
  const [minY, maxY] = [Math.min(...ys), Math.max(...ys)];
  return [
    [minX, minY],
    [maxX, minY],
    [maxX, maxY],
    [minX, maxY],
  ];
}

/**
 * The band a brush of `width` leaves along `path`: one side out, the other side back.
 * Joins are mitred from the neighbouring directions; the ends get a short square cap.
 */
export function ribbon(path: Point2[], width: number): Point2[] {
  const half = width / 2;
  let pts = thin(path, Math.max(half, 0.2));
  const budget = MAX_OUTLINE_POINTS / 2 - 2;
  if (pts.length > budget) {
    const every = pts.length / budget;
    pts = pts.filter((_, i) => i === pts.length - 1 || Math.floor(i % every) === 0);
  }
  if (pts.length === 1) {
    const [x, y] = pts[0];
    return [
      [x - half, y - half],
      [x + half, y - half],
      [x + half, y + half],
      [x - half, y + half],
    ];
  }
  const left: Point2[] = [];
  const right: Point2[] = [];
  for (let i = 0; i < pts.length; i += 1) {
    const prev = pts[Math.max(i - 1, 0)];
    const next = pts[Math.min(i + 1, pts.length - 1)];
    const length = distance(prev, next) || 1;
    const [dx, dy] = [(next[0] - prev[0]) / length, (next[1] - prev[1]) / length];
    // square caps: push the first and last points out along the direction of travel
    const cap = i === 0 ? -half : i === pts.length - 1 ? half : 0;
    const [x, y] = [pts[i][0] + dx * cap, pts[i][1] + dy * cap];
    left.push([x - dy * half, y + dx * half]);
    right.push([x + dy * half, y - dx * half]);
  }
  return [...left, ...right.reverse()];
}

export interface OutlineOptions {
  /** The surface the path was drawn on. */
  surface: Surface;
  /** The model's extent along each axis, so the region reaches through the material. */
  modelSize: { x: number; y: number; z: number };
  /** The kernel body the region targets. */
  bodyId: string;
  /** Painting with a brush this wide; undefined means editing. */
  brushMm?: number;
}

/**
 * Turn a drawn path (model mm, on the surface plane) into a region selection, or null when
 * the path is a tap. The lasso reaches through the whole thickness under the outline, so
 * anything cut or raised there is inside the region by construction.
 */
export function pathToRegion(path: Point2[], options: OutlineOptions): RegionSelection | null {
  if (path.length < 2) return null;
  const xs = path.map((p) => p[0]);
  const ys = path.map((p) => p[1]);
  const painting = options.brushMm !== undefined;
  const spread = Math.max(...xs) - Math.min(...xs) + (Math.max(...ys) - Math.min(...ys));
  if (spread < 0.2 && !painting) return null; // a tap, not an outline

  let outline: Point2[];
  if (painting && !isClosed(path)) {
    outline = ribbon(path, options.brushMm as number); // a sweep is a brush stroke
  } else if (!painting && isStraight(path)) {
    outline = rectangle(path); // a straight drag is a rubber-band rectangle
  } else {
    outline = path.slice(0, MAX_OUTLINE_POINTS);
  }

  const { axis, sign, offset_mm } = options.surface;
  const thickness = Math.max(options.modelSize[axis] * 2, 1);
  const region: LassoRegion = {
    kind: "lasso",
    axis,
    offset_mm,
    depth_mm: thickness,
    points_mm: outline,
  };
  return { region, target: options.bodyId, surface_axis: axis, surface_sign: sign };
}
