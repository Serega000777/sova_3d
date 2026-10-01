/**
 * Floor plans and their markup (T-237, F-087).
 *
 * A plan is flat geometry in millimetres — one scanned room or a whole building with several
 * rooms — and an annotation lives at plan coordinates, never screen pixels, so it stays put
 * when the view pans, zooms or the plan is revised. The same model serves a single room and a
 * merged building (T-197): a building is simply a plan with more than one room.
 */

export type Point = [number, number];

export interface PlanWall {
  a: Point;
  b: Point;
  thickness_mm: number;
}

export interface PlanOpening {
  /** Index into `walls`. */
  wall: number;
  /** Distance from the wall's `a` end to the opening's near edge, mm. */
  offset_mm: number;
  width_mm: number;
  kind: "door" | "window";
}

export interface PlanRoom {
  name: string;
  /** Outline in plan mm, implicitly closed. */
  outline: Point[];
}

export interface FloorPlan {
  id: string;
  name: string;
  walls: PlanWall[];
  openings: PlanOpening[];
  rooms: PlanRoom[];
}

export interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export function wallLength(wall: PlanWall): number {
  return Math.hypot(wall.b[0] - wall.a[0], wall.b[1] - wall.a[1]);
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

export function planBounds(plan: FloorPlan): Bounds | null {
  const points: Point[] = [
    ...plan.walls.flatMap((w) => [w.a, w.b]),
    ...plan.rooms.flatMap((r) => r.outline),
  ];
  return pointsBounds(points);
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
    cleanWalls.push({ a: wall.a, b: wall.b, thickness_mm: thickness });
  }
  const rooms: PlanRoom[] = [];
  for (const r of Array.isArray(raw.rooms) ? raw.rooms : []) {
    const room = r as Record<string, unknown>;
    if (!Array.isArray(room?.outline) || room.outline.length < 3 || !room.outline.every(isPoint)) return null;
    rooms.push({ name: typeof room.name === "string" ? room.name : "Room", outline: room.outline as Point[] });
  }
  const openings: PlanOpening[] = [];
  for (const o of Array.isArray(raw.openings) ? raw.openings : []) {
    const opening = o as Record<string, unknown>;
    if (
      typeof opening?.wall !== "number" ||
      !Number.isInteger(opening.wall) ||
      opening.wall < 0 ||
      opening.wall >= cleanWalls.length ||
      typeof opening.offset_mm !== "number" ||
      typeof opening.width_mm !== "number" ||
      opening.width_mm <= 0
    ) {
      continue; // an opening on a missing wall is dropped, not fatal
    }
    openings.push({
      wall: opening.wall,
      offset_mm: opening.offset_mm,
      width_mm: opening.width_mm,
      kind: opening.kind === "window" ? "window" : "door",
    });
  }
  if (cleanWalls.length === 0 && rooms.length === 0) return null;
  return {
    id: typeof raw.id === "string" && raw.id ? raw.id : "imported-plan",
    name: typeof raw.name === "string" && raw.name ? raw.name : "Imported plan",
    walls: cleanWalls,
    openings,
    rooms,
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
    const base = {
      id: a.id,
      author: typeof a.author === "string" ? a.author : "",
      created_at: typeof a.created_at === "string" ? a.created_at : new Date(0).toISOString(),
      status: a.status === "resolved" ? ("resolved" as const) : ("open" as const),
      note: typeof a.note === "string" ? a.note : "",
      colour: typeof a.colour === "string" ? a.colour : ANNOTATION_COLOURS[0],
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
