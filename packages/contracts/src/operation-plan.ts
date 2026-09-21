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

export type Profile =
  | { kind: "rectangle"; width_mm: number; depth_mm: number }
  | { kind: "circle"; diameter_mm: number }
  | { kind: "polygon"; points_mm: Vec2[] };

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

export interface Extrude extends OperationBase {
  type: "extrude";
  profile: Profile;
  height_mm: number;
  origin_mm?: Vec3;
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
  | Extrude
  | Boolean_
  | Fillet
  | Chamfer
  | AddHole
  | Shell
  | Translate
  | Rotate
  | LinearPattern
  | CircularPattern
  | SetDimensions
  | SetParameter;

export type OperationType = Operation["type"];

export const OPERATION_TYPES: readonly OperationType[] = [
  "create_box",
  "create_cylinder",
  "extrude",
  "boolean",
  "fillet",
  "chamfer",
  "add_hole",
  "shell",
  "translate",
  "rotate",
  "linear_pattern",
  "circular_pattern",
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
