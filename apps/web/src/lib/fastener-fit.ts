import type {
  FastenerAccepted,
  FastenerCatalogItem,
  FastenerCreate,
  FitTestReport,
  Job,
  OperationStack,
  SceneGraph,
} from "@physical-ai/contracts";

export interface ExactPlanarHole {
  id: string;
  diameterMm: number;
  depthMm: number | null;
  positionMm: [number, number];
  faceAxis: "x" | "y" | "z";
  faceSign: "+" | "-";
}

export interface VerifiedFastenerFit {
  fitTestId: string;
  report: FitTestReport;
}

function finitePositive(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function sameNumber(left: unknown, right: number): boolean {
  return typeof left === "number" && Number.isFinite(left) && Math.abs(left - right) <= 0.000_001;
}

/** Only active exact-CAD holes on one of the six supported planar faces are selectable. */
export function exactPlanarHoles(stack: OperationStack, versionId: string): ExactPlanarHole[] {
  if (stack.version_id !== versionId || !Array.isArray(stack.operations)) return [];
  return stack.operations.flatMap((operation) => {
    const params = record(operation.params);
    if (!params) return [];
    const face = record(params.face);
    const position = params.position_mm;
    const diameter = params.diameter_mm;
    const rawDepth = params.depth_mm;
    const depth = rawDepth === null || rawDepth === undefined ? null : rawDepth;
    if (
      !operation.enabled
      || operation.type !== "add_hole"
      || typeof operation.id !== "string"
      || !operation.id.trim()
      || face?.kind !== "face_by_normal"
      || !["x", "y", "z"].includes(String(face.axis))
      || !["+", "-"].includes(String(face.sign))
      || !Array.isArray(position)
      || position.length !== 2
      || !position.every((value) => typeof value === "number" && Number.isFinite(value))
      || !finitePositive(diameter)
      || (depth !== null && !finitePositive(depth))
    ) return [];
    return [{
      id: operation.id,
      diameterMm: diameter,
      depthMm: depth,
      positionMm: [position[0] as number, position[1] as number],
      faceAxis: face.axis as ExactPlanarHole["faceAxis"],
      faceSign: face.sign as ExactPlanarHole["faceSign"],
    }];
  });
}

export function fastenerAcceptedMatches(
  accepted: FastenerAccepted,
  requested: FastenerCreate,
  workspaceId: string,
  catalogItem: FastenerCatalogItem,
): boolean {
  const acceptedRecord = record(accepted);
  const acceptedJob = record(acceptedRecord?.job);
  const fastener = record(acceptedRecord?.fastener);
  if (!acceptedJob || !fastener) return false;
  return requested.workspace_id === workspaceId
    && acceptedJob.type === "execute_plan"
    && fastener.schema_version === 1
    && fastener.size === requested.size
    && sameNumber(fastener.length_mm, requested.length_mm)
    && fastener.head === requested.head
    && fastener.drive === requested.drive
    && fastener.thread_geometry === "smooth_nominal_envelope"
    && fastener.drive_recess_modeled === false
    && fastener.geometry_reference === "head_seat_z0"
    && catalogItem.size === requested.size
    && sameNumber(fastener.nominal_mm, catalogItem.nominal_mm)
    && finitePositive(fastener.nominal_mm)
    && finitePositive(fastener.head_diameter_mm)
    && finitePositive(fastener.head_height_mm);
}

/** Bind the produced version to the accepted fastener project and current workspace. */
export function verifiedFastenerVersion(
  job: Job,
  accepted: FastenerAccepted,
  workspaceId: string,
): string | null {
  const versionId = (job.result as { version_id?: unknown } | null)?.version_id;
  const acceptedRecord = record(accepted);
  const acceptedJob = record(acceptedRecord?.job);
  if (!acceptedRecord || !acceptedJob) return null;
  return job.status === "succeeded"
    && job.id === acceptedJob.job_id
    && job.type === "execute_plan"
    && job.workspace_id === workspaceId
    && job.project_id === acceptedRecord.project_id
    && typeof versionId === "string"
    && versionId.length > 0
    ? versionId
    : null;
}

/** Reject a successful-but-substituted job or report before it can enable assembly creation. */
export function verifiedFastenerFit(
  job: Job,
  acceptedJobId: string,
  workspaceId: string,
  targetVersionId: string,
  fastenerVersionId: string,
  hole: ExactPlanarHole,
  requested: FastenerCreate,
  expectedFastener: FastenerAccepted["fastener"],
): VerifiedFastenerFit | null {
  const result = job.result as {
    fit_test_id?: unknown;
    version_a_id?: unknown;
    version_b_id?: unknown;
    report?: unknown;
  } | null;
  if (
    job.status !== "succeeded"
    || job.id !== acceptedJobId
    || job.type !== "fit_test"
    || job.workspace_id !== workspaceId
    || job.project_version_id !== targetVersionId
    || result?.version_a_id !== targetVersionId
    || result.version_b_id !== fastenerVersionId
    || typeof result.fit_test_id !== "string"
    || !result.fit_test_id
    || !result.report
    || typeof result.report !== "object"
    || Array.isArray(result.report)
  ) return null;
  const report = record(result.report);
  const fastener = record(report?.fastener);
  const metadata = record(fastener?.fastener);
  const limitations = fastener?.limitations;
  if (
    !report
    || !fastener
    || !metadata
    || fastener.schema_version !== 1
    || fastener.hole_operation_id !== hole.id
    || !sameNumber(fastener.hole_diameter_mm, hole.diameterMm)
    || !finitePositive(fastener.hole_depth_mm)
    || !Number.isFinite(fastener.radial_clearance_mm)
    || !finitePositive(fastener.engagement_mm)
    || typeof fastener.head_seated !== "boolean"
    || typeof fastener.geometry_compatible !== "boolean"
    || metadata.size !== requested.size
    || metadata.schema_version !== 1
    || !sameNumber(metadata.length_mm, requested.length_mm)
    || metadata.head !== requested.head
    || metadata.drive !== requested.drive
    || metadata.thread_geometry !== "smooth_nominal_envelope"
    || metadata.drive_recess_modeled !== false
    || metadata.geometry_reference !== "head_seat_z0"
    || !sameNumber(metadata.nominal_mm, expectedFastener.nominal_mm)
    || !sameNumber(metadata.head_diameter_mm, expectedFastener.head_diameter_mm)
    || !sameNumber(metadata.head_height_mm, expectedFastener.head_height_mm)
    || !Array.isArray(limitations)
    || limitations.length === 0
    || !limitations.every((item) => typeof item === "string" && item.trim())
  ) return null;
  if (!finitePositive(metadata.nominal_mm)) return null;
  const expectedClearance = ((fastener.hole_diameter_mm as number) - metadata.nominal_mm) / 2;
  if (Math.abs(expectedClearance - (fastener.radial_clearance_mm as number)) > 0.001_1) return null;
  return { fitTestId: result.fit_test_id, report: report as unknown as FitTestReport };
}

export function verifiedFastenerAssembly(
  scene: SceneGraph,
  sourceVersionId: string,
): SceneGraph | null {
  if (!Array.isArray(scene.nodes)) return null;
  const rows = scene.nodes.flatMap((node) => record(node) ? [node] : []);
  const ids = new Set(rows.flatMap((node) => typeof node.id === "string" ? [node.id] : []));
  const assembly = rows.find((node) => node.id === "assembly");
  const partA = rows.find((node) => node.id === "part_a");
  const fastener = rows.find((node) => node.id === "fastener");
  return scene.version_id !== sourceVersionId
    && typeof scene.version_id === "string"
    && scene.version_id.length > 0
    && scene.parent_version_id === sourceVersionId
    && ids.size === scene.nodes.length
    && ids.has("assembly")
    && ids.has("part_a")
    && ids.has("fastener")
    && !ids.has("part_b")
    && assembly?.kind === "group"
    && assembly.parent_id === null
    && partA?.kind === "object"
    && partA.parent_id === "assembly"
    && fastener?.kind === "object"
    && fastener.parent_id === "assembly"
    && typeof partA.asset_id === "string"
    && typeof fastener.asset_id === "string"
    ? scene
    : null;
}
