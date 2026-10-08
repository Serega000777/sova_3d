/**
 * OperationPlan — the only artifact an AI planner is allowed to emit.
 * Mirrors ../operation-plan.schema.json (schema_version 1), which is generated
 * from services/api/app/geometry/operations.py. Geometry execution never
 * starts while `required_clarifications` is non-empty.
 *
 * Every length is millimetres, every angle degrees. A body is named after the
 * operation that created it; edges/faces are addressed by deterministic
 * geometric selectors so a plan replays identically.
 */
export const OPERATION_PLAN_SCHEMA_VERSION = 1 as const;

export type Axis = "x" | "y" | "z";
export type Vec3 = [number, number, number];
export type Vec2 = [number, number];

export type FaceSelector =
  | { kind: "face_by_normal"; axis: Axis; sign?: "+" | "-" }
  | { kind: "all_faces" };

export type EdgeSelector =
  | { kind: "all_edges" }
  | { kind: "edges_parallel_to"; axis: Axis; outer?: boolean }
  | { kind: "edges_of_face"; face: FaceSelector };

export type SketchConstraint =
  | { kind: "fixed"; point: number }
  | { kind: "horizontal" | "vertical"; start: number; end: number }
  | { kind: "coincident"; first: number; second: number }
  | { kind: "distance"; start: number; end: number; distance_mm: number }
  | {
      kind: "equal_length" | "parallel" | "perpendicular";
      first_start: number;
      first_end: number;
      second_start: number;
      second_end: number;
    };

export type SketchSegment =
  | { kind: "line" }
  | { kind: "arc"; center_mm: Vec2; clockwise?: boolean }
  | { kind: "spline"; through_points_mm: Vec2[] }
  | {
      kind: "nurbs";
      /** Interior poles; the segment endpoints are the first and last poles. */
      control_points_mm: Vec2[];
      degree: number;
      weights: number[];
      knots: number[];
      multiplicities: number[];
    };

export type Profile =
  | { kind: "rectangle"; width_mm: number; depth_mm: number }
  | { kind: "circle"; diameter_mm: number }
  | { kind: "polygon"; points_mm: Vec2[] }
  | {
      kind: "sketch";
      points_mm: Vec2[];
      /** Segment i joins point i to point i+1; omitted means the legacy all-line loop. */
      segments?: SketchSegment[] | null;
      constraints?: SketchConstraint[];
      tolerance_mm?: number;
    };

export interface ProfileSection {
  profile: Profile;
  origin_mm?: Vec3;
  /** Plane normal; defaults to +Z. */
  normal?: Vec3;
  /** In-plane +X direction, perpendicular to normal; defaults to +X. */
  x_direction?: Vec3;
}

interface OperationBase {
  /** `^[a-z][a-z0-9_]{0,63}$` — also the name of the body a creator produces. */
  id: string;
  schema_version: typeof OPERATION_PLAN_SCHEMA_VERSION;
}

export interface CreateBox extends OperationBase {
  type: "create_box";
  width_mm: number;
  depth_mm: number;
  height_mm: number;
  origin_mm?: Vec3;
  centered?: boolean;
}

export interface CreateCylinder extends OperationBase {
  type: "create_cylinder";
  diameter_mm: number;
  height_mm: number;
  axis?: Axis;
  origin_mm?: Vec3;
}

export interface CreateSphere extends OperationBase {
  type: "create_sphere";
  diameter_mm: number;
  origin_mm?: Vec3;
}

export interface CreateCone extends OperationBase {
  type: "create_cone";
  bottom_diameter_mm: number;
  top_diameter_mm?: number;
  height_mm: number;
  axis?: Axis;
  origin_mm?: Vec3;
}

export interface CreateTorus extends OperationBase {
  type: "create_torus";
  outer_diameter_mm: number;
  tube_diameter_mm: number;
  axis?: Axis;
  origin_mm?: Vec3;
}

export interface Extrude extends OperationBase {
  type: "extrude";
  profile: Profile;
  height_mm: number;
  origin_mm?: Vec3;
  /** Extrusion and profile-plane normal; defaults to +Z. */
  normal?: Vec3;
  /** In-plane +X direction, perpendicular to normal; defaults to +X. */
  x_direction?: Vec3;
}

export interface Loft extends OperationBase {
  type: "loft";
  sections: ProfileSection[];
  ruled?: boolean;
}

export interface Sweep extends OperationBase {
  type: "sweep";
  profile: Profile;
  path_mm: Vec3[];
}

export interface Revolve extends OperationBase {
  type: "revolve";
  profile: Profile;
  axis?: Axis;
  angle_deg?: number;
  origin_mm?: Vec3;
}

export interface NurbsSurface extends OperationBase {
  type: "nurbs_surface";
  /** Rectangular U rows × V columns of exact surface poles in model millimetres. */
  control_points_mm: Vec3[][];
  /** Positive rational weights with the same dimensions as control_points_mm. */
  weights: number[][];
  u_degree: number;
  v_degree: number;
  u_knots: number[];
  v_knots: number[];
  u_multiplicities: number[];
  v_multiplicities: number[];
  /** Normal offset used to close the patch into a solid. */
  thickness_mm: number;
  tolerance_mm?: number;
}

export interface CylindricalSurface {
  kind: "cylinder";
  origin_mm: Vec3;
  axis_direction: Vec3;
  reference_direction: Vec3;
  radius_mm: number;
}

export interface ConicalSurface {
  kind: "cone";
  origin_mm: Vec3;
  axis_direction: Vec3;
  reference_direction: Vec3;
  radius_mm: number;
  half_angle_deg: number;
}

export interface SphericalSurface {
  kind: "sphere";
  center_mm: Vec3;
  polar_axis_direction: Vec3;
  reference_direction: Vec3;
  radius_mm: number;
}

export type AnalyticSurface = CylindricalSurface | ConicalSurface | SphericalSurface;

export interface AnalyticSurfacePatch extends OperationBase {
  type: "analytic_surface_patch";
  surface: AnalyticSurface;
  boundary_uv: Vec2[];
  thickness_mm: number;
  tolerance_mm?: number;
}

export interface Boolean_ extends OperationBase {
  type: "boolean";
  op: "cut" | "fuse" | "common";
  target: string;
  tool: string;
}

export interface Fillet extends OperationBase {
  type: "fillet";
  target: string;
  edges: EdgeSelector;
  radius_mm: number;
}

export interface Chamfer extends OperationBase {
  type: "chamfer";
  target: string;
  edges: EdgeSelector;
  distance_mm: number;
}

/** F-007: hollow the body to a wall; `open_face` removes that face so the hollow opens there. */
export interface Shell extends OperationBase {
  type: "shell";
  target: string;
  thickness_mm: number;
  open_face?: FaceSelector | null;
}

export interface AddHole extends OperationBase {
  type: "add_hole";
  target: string;
  face: FaceSelector;
  position_mm: Vec2;
  diameter_mm: number;
  /** Omit for a through hole. */
  depth_mm?: number | null;
}

export interface Translate extends OperationBase {
  type: "translate";
  target: string;
  offset_mm: Vec3;
}

export interface Rotate extends OperationBase {
  type: "rotate";
  target: string;
  axis: Axis;
  angle_deg: number;
  origin_mm?: Vec3;
}

export interface LinearPattern extends OperationBase {
  type: "linear_pattern";
  target: string;
  axis: Axis;
  count: number;
  spacing_mm: number;
}

export interface CircularPattern extends OperationBase {
  type: "circular_pattern";
  target: string;
  axis: Axis;
  count: number;
  angle_deg?: number;
  origin_mm?: Vec3;
}

export interface Mirror extends OperationBase {
  type: "mirror";
  target: string;
  axis: Axis;
  offset_mm?: number;
  keep_original?: boolean;
}

export interface SetDimensions extends OperationBase {
  type: "set_dimensions";
  target: string;
  width_mm?: number | null;
  depth_mm?: number | null;
  height_mm?: number | null;
}

export interface SetParameter extends OperationBase {
  type: "set_parameter";
  operation: string;
  parameter: string;
  value: number;
}

export type Operation =
  | CreateBox
  | CreateCylinder
  | CreateSphere
  | CreateCone
  | CreateTorus
  | Extrude
  | Loft
  | Sweep
  | Revolve
  | NurbsSurface
  | AnalyticSurfacePatch
  | Boolean_
  | Fillet
  | Chamfer
  | AddHole
  | Shell
  | Translate
  | Rotate
  | LinearPattern
  | CircularPattern
  | Mirror
  | SetDimensions
  | SetParameter;

export type OperationType = Operation["type"];

export const OPERATION_TYPES: readonly OperationType[] = [
  "create_box",
  "create_cylinder",
  "create_sphere",
  "create_cone",
  "create_torus",
  "extrude",
  "loft",
  "sweep",
  "revolve",
  "nurbs_surface",
  "analytic_surface_patch",
  "boolean",
  "fillet",
  "chamfer",
  "add_hole",
  "shell",
  "translate",
  "rotate",
  "linear_pattern",
  "circular_pattern",
  "mirror",
  "set_dimensions",
  "set_parameter",
];

export interface OperationPlan {
  schema_version: typeof OPERATION_PLAN_SCHEMA_VERSION;
  goal: string;
  assumptions?: string[];
  required_clarifications?: string[];
  operations: Operation[];
  validation_steps?: string[];
  expected_outputs?: string[];
}
