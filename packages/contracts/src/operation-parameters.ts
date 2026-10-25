export interface OperationParameterSource {
  id: string;
  type: string;
  enabled: boolean;
  params: Record<string, unknown>;
}

export interface EditableOperationParameter {
  operationId: string;
  operationType: string;
  parameter: string;
  value: number;
  unit: "mm" | "deg";
  positional: boolean;
}

type ScalarSource = string | readonly [string, string];

const ORIGIN = ["origin_x_mm", "origin_y_mm", "origin_z_mm"] as const;
const POSITION = ["position_x_mm", "position_y_mm", "position_z_mm"] as const;
const CENTRE = ["centre_x_mm", "centre_y_mm", "centre_z_mm"] as const;
const OFFSET = ["offset_x_mm", "offset_y_mm", "offset_z_mm"] as const;

const EDITABLE: Record<string, readonly ScalarSource[]> = {
  create_box: ["width_mm", "depth_mm", "height_mm", ...ORIGIN],
  create_hip_roof: ["width_mm", "depth_mm", "height_mm", ...ORIGIN],
  create_cylinder: ["diameter_mm", "height_mm", ...ORIGIN],
  create_sphere: ["diameter_mm", ...ORIGIN],
  create_cone: ["bottom_diameter_mm", "top_diameter_mm", "height_mm", ...ORIGIN],
  create_torus: ["outer_diameter_mm", "tube_diameter_mm", ...ORIGIN],
  extrude: ["height_mm", ...ORIGIN],
  revolve: ["angle_deg", ...ORIGIN],
  nurbs_surface: ["thickness_mm"],
  analytic_surface_patch: ["thickness_mm"],
  fillet: ["radius_mm"],
  chamfer: ["distance_mm"],
  add_hole: ["diameter_mm", "depth_mm", ...POSITION],
  add_internal_thread: ["major_diameter_mm", "minor_diameter_mm", "pitch_mm", "depth_mm", ...POSITION],
  add_hole_pattern: ["diameter_mm", "depth_mm", ...CENTRE],
  shell: ["thickness_mm"],
  translate: [...OFFSET],
  rotate: ["angle_deg", ...ORIGIN],
  linear_pattern: ["spacing_mm"],
  circular_pattern: ["angle_deg", ...ORIGIN],
  mirror: ["offset_mm"],
};

const PATTERN_EDITABLE: Record<string, readonly ScalarSource[]> = {
  linear: [["pitch_mm", "pattern"], ["angle_deg", "pattern"]],
  grid: [["pitch_x_mm", "pattern"], ["pitch_y_mm", "pattern"]],
  circular: [["radius_mm", "pattern"], ["start_angle_deg", "pattern"]],
};

function vectorValue(params: Record<string, unknown>, parameter: string): number | null {
  const match = /^(origin|position|centre|offset)_([xyz])_mm$/.exec(parameter);
  if (!match) return null;
  const vector = params[`${match[1]}_mm`];
  if (!Array.isArray(vector)) return null;
  const index = { x: 0, y: 1, z: 2 }[match[2] as "x" | "y" | "z"];
  const value = vector[index];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function sourceValue(params: Record<string, unknown>, source: ScalarSource): number | null {
  const parameter = typeof source === "string" ? source : source[0];
  if (typeof source === "string") {
    const direct = params[parameter];
    if (typeof direct === "number" && Number.isFinite(direct)) return direct;
    return vectorValue(params, parameter);
  }
  const parent = params[source[1]];
  if (!parent || typeof parent !== "object" || Array.isArray(parent)) return null;
  const value = (parent as Record<string, unknown>)[parameter];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function isPositional(parameter: string): boolean {
  return /^(origin|position|centre|offset)_[xyz]_mm$/.test(parameter) || parameter === "offset_mm" || parameter === "start_angle_deg";
}

/** Numeric parameters that the deterministic OCCT replay kernel can edit exactly. */
export function editableOperationParameters(
  operations: readonly OperationParameterSource[],
): Record<string, EditableOperationParameter[]> {
  const result: Record<string, EditableOperationParameter[]> = {};
  const operationIndexes = new Map(operations.map((operation, index) => [operation.id, index]));
  for (const operation of operations) {
    const sources = [...(EDITABLE[operation.type] ?? [])];
    if (operation.type === "add_hole_pattern") {
      const pattern = operation.params.pattern;
      const kind = pattern && typeof pattern === "object" && !Array.isArray(pattern)
        ? (pattern as Record<string, unknown>).kind
        : null;
      if (typeof kind === "string") sources.push(...(PATTERN_EDITABLE[kind] ?? []));
    }
    const parameters = sources.flatMap((source) => {
      const parameter = typeof source === "string" ? source : source[0];
      const value = sourceValue(operation.params, source);
      return value === null
        ? []
        : [{
            operationId: operation.id,
            operationType: operation.type,
            parameter,
            value,
            unit: parameter.endsWith("_deg") ? "deg" as const : "mm" as const,
            positional: isPositional(parameter),
          }];
    });
    if (parameters.length) result[operation.id] = parameters;
  }

  // A stored set_parameter is an immutable feature-tree row. Its latest enabled value is
  // the effective value shown for the original operation and can itself be superseded.
  for (const [index, operation] of operations.entries()) {
    if (!operation.enabled || operation.type !== "set_parameter") continue;
    const target = operation.params.operation;
    const parameter = operation.params.parameter;
    const value = operation.params.value;
    if (typeof target !== "string" || typeof parameter !== "string" || typeof value !== "number" || !Number.isFinite(value)) continue;
    if ((operationIndexes.get(target) ?? Number.POSITIVE_INFINITY) >= index) continue;
    const descriptor = result[target]?.find((item) => item.parameter === parameter);
    if (descriptor) descriptor.value = value;
  }
  return result;
}

export function operationParameterValue(
  parameter: EditableOperationParameter,
  input: string | number,
): number | null {
  const normalized = typeof input === "number" ? input : input.trim().replace(",", ".");
  if (normalized === "") return null;
  const value = typeof normalized === "number" ? normalized : Number(normalized);
  if (!Number.isFinite(value) || value <= -10_000 || value > 10_000) return null;
  if (!parameter.positional && value <= 0) return null;
  return value;
}

export function setParameterOperation(
  parameter: EditableOperationParameter,
  value: number,
): { type: "set_parameter"; operation: string; parameter: string; value: number } {
  return {
    type: "set_parameter",
    operation: parameter.operationId,
    parameter: parameter.parameter,
    value,
  };
}
