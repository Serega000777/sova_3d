/**
 * Direct mesh editing and surface details (T-235 / T-236, F-086): the request shapes the API
 * accepts and the translation from what a person selected in the viewer into them.
 *
 * Selections travel as millimetre coordinates, not indices: the viewer's vertex, edge and
 * face ids belong to a welded copy of the mesh it drew, so positions are the one thing the
 * client and the worker can both find again.
 */
import type { Vec3 } from "./operation-plan.js";
import type { ComponentKind, MeshTopology } from "./topology.js";

export interface MeshSelection {
  kind: ComponentKind;
  /** 1 point per vertex, 2 per edge, 3 per face. */
  points_mm: Vec3[];
}

export type MeshEditOperation =
  | { op: "move"; selection: MeshSelection; delta_mm?: Vec3; along_normal_mm?: number }
  | { op: "extrude"; selection: MeshSelection & { kind: "face" }; distance_mm: number }
  | { op: "inset"; selection: MeshSelection & { kind: "face" }; amount_mm: number }
  | { op: "delete_faces"; selection: MeshSelection & { kind: "face" }; fill?: boolean }
  | { op: "bevel_edges"; selection: MeshSelection & { kind: "edge" }; width_mm: number; segments?: number }
  | SurfaceDetailOperation;

export interface DetailArea {
  width_mm: number;
  length_mm: number;
  rotation_deg?: number;
}

export type DetailProfile =
  | { shape: "circle"; diameter_mm: number }
  | { shape: "square"; width_mm: number; height_mm?: number; rotation_deg?: number }
  | { shape: "ribs"; area: DetailArea; pitch_mm: number; rib_width_mm: number; angle_deg?: number }
  | { shape: "knurl"; area: DetailArea; pattern?: "straight" | "diamond"; pitch_mm: number; angle_deg?: number };

export interface SurfaceDetailOperation {
  op: "detail";
  at_mm: Vec3;
  normal_hint?: Vec3;
  profile: DetailProfile;
  mode?: "raised" | "recessed";
  depth_mm: number;
}

export interface MeshEditRequest {
  operations: MeshEditOperation[];
  /** Check and report only (footprint, triangle estimate); no version is created. */
  preview?: boolean;
  /** Triangles of the mesh the selection was made on; a changed mesh is refused as stale. */
  expected_faces?: number;
  tolerance_mm?: number;
  label?: string | null;
  /** Required to edit a parametric version's mesh; it becomes a plain mesh. */
  convert_to_mesh?: boolean;
  /** Direct geometry object in an explicit scene; selections are in displayed world mm. */
  scene_node_id?: string | null;
}

export interface MeshEditReport {
  ok: boolean;
  code?: string | null;
  message?: string | null;
  failed_operation?: number | null;
  applied: { op: string; detail: Record<string, unknown> }[];
  before?: MeshStats | null;
  after?: MeshStats | null;
  warnings: string[];
  repairs: string[];
  preview?: { footprints_mm: Vec3[][]; estimated_added_triangles: number } | null;
}

export interface MeshStats {
  faces: number;
  vertices: number;
  volume_mm3: number | null;
  watertight: boolean;
  bbox_mm: [Vec3, Vec3];
}

function position(topology: MeshTopology, vertex: number): Vec3 {
  const p = topology.positions;
  return [p[vertex * 3] as number, p[vertex * 3 + 1] as number, p[vertex * 3 + 2] as number];
}

/** The picked components as coordinates the worker can find again. */
export function selectionToPoints(
  topology: MeshTopology,
  kind: ComponentKind,
  ids: Iterable<number>,
): MeshSelection {
  const points: Vec3[] = [];
  for (const id of ids) {
    if (kind === "vertex") points.push(position(topology, id));
    else if (kind === "edge") {
      points.push(position(topology, topology.edges[id * 2] as number));
      points.push(position(topology, topology.edges[id * 2 + 1] as number));
    } else {
      for (let c = 0; c < 3; c += 1) points.push(position(topology, topology.faces[id * 3 + c] as number));
    }
  }
  return { kind, points_mm: points };
}

/** How many triangles the source mesh had, for the worker's stale-selection check. */
export function sourceTriangleCount(topology: MeshTopology): number {
  return topology.cornerVertex.length / 3;
}

/** Centre and outward normal of a single selected face, to anchor a surface detail on it. */
export function faceAnchor(topology: MeshTopology, face: number): { at_mm: Vec3; normal: Vec3 } {
  const a = position(topology, topology.faces[face * 3] as number);
  const b = position(topology, topology.faces[face * 3 + 1] as number);
  const c = position(topology, topology.faces[face * 3 + 2] as number);
  const ux = b[0] - a[0];
  const uy = b[1] - a[1];
  const uz = b[2] - a[2];
  const vx = c[0] - a[0];
  const vy = c[1] - a[1];
  const vz = c[2] - a[2];
  const nx = uy * vz - uz * vy;
  const ny = uz * vx - ux * vz;
  const nz = ux * vy - uy * vx;
  const length = Math.hypot(nx, ny, nz) || 1;
  return {
    at_mm: [(a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3, (a[2] + b[2] + c[2]) / 3],
    normal: [nx / length, ny / length, nz / length],
  };
}

const FAILURES: Record<string, { en: string; ru: string }> = {
  stale_selection: {
    en: "The selection no longer matches the model. Select again.",
    ru: "Выбор больше не совпадает с моделью. Выберите заново.",
  },
  below_tolerance: {
    en: "That feature is smaller than the tolerance. Make it larger.",
    ru: "Деталь меньше допуска. Сделайте её крупнее.",
  },
  footprint_leaves_surface: {
    en: "The feature does not fit on one flat surface. Make it smaller or move it.",
    ru: "Деталь не помещается на одной плоскости. Уменьшите её или сдвиньте.",
  },
  would_cut_through: {
    en: "The wall is too thin for that depth. Use a shallower cut.",
    ru: "Стенка слишком тонкая для такой глубины. Сделайте вырез мельче.",
  },
  surface_ambiguous: {
    en: "The point sits on an edge. Click inside one face.",
    ru: "Точка лежит на ребре. Нажмите внутри одной грани.",
  },
  off_surface: {
    en: "The chosen point is not on the model.",
    ru: "Выбранная точка не на модели.",
  },
  needs_watertight: {
    en: "This operation needs a closed (watertight) mesh. Repair the model first.",
    ru: "Для этой операции нужна замкнутая сетка. Сначала почините модель.",
  },
  inset_too_large: {
    en: "That inset folds the faces over. Use a smaller amount.",
    ru: "Такой отступ заворачивает грани. Уменьшите значение.",
  },
  nothing_to_bevel: {
    en: "None of the selected edges can be bevelled (smooth, concave or open).",
    ru: "Выбранные рёбра нельзя скруглить (гладкие, вогнутые или открытые).",
  },
  broke_watertight: {
    en: "The edit would break the solid, so it was not applied.",
    ru: "Правка нарушила бы замкнутость модели, поэтому не применена.",
  },
  too_many_features: {
    en: "Too many ribs or grooves. Use a larger pitch or a smaller area.",
    ru: "Слишком много рёбер или канавок. Увеличьте шаг или уменьшите область.",
  },
  hole_not_filled: {
    en: "The hole could not be filled. Select a smaller or simpler region.",
    ru: "Отверстие не удалось закрыть. Выберите область поменьше и попроще.",
  },
};

/** One readable sentence for a failed edit, falling back to the worker's own message. */
export function describeEditFailure(
  code: string | null | undefined,
  message: string | null | undefined,
  language: "en" | "ru",
): string {
  const known = code ? FAILURES[code] : undefined;
  if (known) return known[language];
  return message || (language === "ru" ? "Не удалось применить правку." : "The edit could not be applied.");
}

/** The vertices a detail footprint outlines, for drawing the preview over the model. */
export function footprintSegments(footprint: readonly Vec3[]): [Vec3, Vec3][] {
  return footprint.map((p, i) => [p, footprint[(i + 1) % footprint.length] as Vec3]);
}
