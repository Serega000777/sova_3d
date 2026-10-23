/** Runtime-safe view of the worker's conversion/integrity report. */

export type IntegrityStatus = "pass" | "warn" | "fail";

export interface IntegrityCheck {
  id: string;
  status: IntegrityStatus;
  message: string;
  expected: number | string | boolean | null;
  actual: number | string | boolean | null;
  tolerance: number | null;
}

export interface IntegrityGeometrySummary {
  format: string;
  bboxSizeMm: [number, number, number] | null;
  faces: number | null;
  vertices: number | null;
  watertight: boolean | null;
  volumeMm3: number | null;
  surfaceAreaMm2: number | null;
  materialCount: number | null;
  textureCount: number | null;
  nodeCount: number | null;
  meshCount: number | null;
  animationCount: number | null;
  cameraCount: number | null;
  lightCount: number | null;
}

export interface IntegrityReport {
  schemaVersion: 1;
  sourceFormat: string;
  targetFormat: string;
  printableGate: boolean;
  status: IntegrityStatus;
  checks: IntegrityCheck[];
  summary: string;
  source: IntegrityGeometrySummary;
  output: IntegrityGeometrySummary;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function nullableFinite(value: unknown): number | null | undefined {
  return value === null ? null : finite(value) ?? undefined;
}

function nullableCount(value: unknown): number | null | undefined {
  return value === null || value === undefined ? null : count(value) ?? undefined;
}

function status(value: unknown): IntegrityStatus | null {
  return value === "pass" || value === "warn" || value === "fail" ? value : null;
}

function scalar(value: unknown): number | string | boolean | null | undefined {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  return finite(value) ?? undefined;
}

function geometry(value: unknown): IntegrityGeometrySummary | null {
  const raw = record(value);
  if (!raw || typeof raw.format !== "string" || raw.format.trim() === "") return null;
  let bboxSizeMm: [number, number, number] | null = null;
  if (raw.bbox_size_mm !== null) {
    if (!Array.isArray(raw.bbox_size_mm) || raw.bbox_size_mm.length !== 3) return null;
    const parsed = raw.bbox_size_mm.map(finite);
    if (parsed.some((item) => item === null)) return null;
    bboxSizeMm = parsed as [number, number, number];
  }
  const faces = nullableCount(raw.faces);
  const vertices = nullableCount(raw.vertices);
  const volumeMm3 = nullableFinite(raw.volume_mm3);
  const surfaceAreaMm2 = nullableFinite(raw.surface_area_mm2);
  const materialCount = nullableCount(raw.material_count);
  const textureCount = nullableCount(raw.texture_count);
  const nodeCount = nullableCount(raw.node_count);
  const meshCount = nullableCount(raw.mesh_count);
  const animationCount = nullableCount(raw.animation_count);
  const cameraCount = nullableCount(raw.camera_count);
  const lightCount = nullableCount(raw.light_count);
  if (
    faces === undefined ||
    vertices === undefined ||
    volumeMm3 === undefined ||
    surfaceAreaMm2 === undefined ||
    materialCount === undefined ||
    textureCount === undefined ||
    nodeCount === undefined ||
    meshCount === undefined ||
    animationCount === undefined ||
    cameraCount === undefined ||
    lightCount === undefined ||
    !(raw.watertight === null || typeof raw.watertight === "boolean")
  ) {
    return null;
  }
  return {
    format: raw.format,
    bboxSizeMm,
    faces,
    vertices,
    watertight: raw.watertight,
    volumeMm3,
    surfaceAreaMm2,
    materialCount,
    textureCount,
    nodeCount,
    meshCount,
    animationCount,
    cameraCount,
    lightCount,
  };
}
/** Reject partial or forged reports instead of showing a green model-check result. */
export function parseIntegrityReport(value: unknown): IntegrityReport | null {
  const raw = record(value);
  if (
    !raw ||
    raw.schema_version !== 1 ||
    typeof raw.source_format !== "string" ||
    typeof raw.target_format !== "string" ||
    typeof raw.printable_gate !== "boolean" ||
    typeof raw.summary !== "string" ||
    !Array.isArray(raw.checks)
  ) {
    return null;
  }
  const reportStatus = status(raw.status);
  const source = geometry(raw.source);
  const output = geometry(raw.output);
  if (!reportStatus || !source || !output) return null;
  const checks: IntegrityCheck[] = [];
  for (const item of raw.checks) {
    const check = record(item);
    if (!check || typeof check.id !== "string" || typeof check.message !== "string") return null;
    const checkStatus = status(check.status);
    const expected = scalar(check.expected ?? null);
    const actual = scalar(check.actual ?? null);
    const tolerance = nullableFinite(check.tolerance ?? null);
    if (!checkStatus || expected === undefined || actual === undefined || tolerance === undefined) {
      return null;
    }
    checks.push({
      id: check.id,
      status: checkStatus,
      message: check.message,
      expected,
      actual,
      tolerance,
    });
  }
  return {
    schemaVersion: 1,
    sourceFormat: raw.source_format,
    targetFormat: raw.target_format,
    printableGate: raw.printable_gate,
    status: reportStatus,
    checks,
    summary: raw.summary,
    source,
    output,
  };
}
