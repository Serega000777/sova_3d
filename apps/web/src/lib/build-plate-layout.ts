import type { SplitProvenance, Version } from "@physical-ai/contracts";

function finitePositive(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function finiteCoordinate(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

type Footprint = { x: number; y: number; width: number; depth: number };

function validPlacementGeometry(
  layout: SplitProvenance,
  requestedMarginMm: number,
  requestedGapMm: number,
): boolean {
  const bed = layout.layout_bed_mm;
  if (!bed || !finitePositive(bed[0]) || !finitePositive(bed[1]) || !finitePositive(bed[2])) {
    return false;
  }
  const [bedX, bedY, bedZ] = bed;
  const footprints: Footprint[] = [];
  for (const part of layout.parts) {
    const [sourceX, sourceY, sourceZ] = part.extents_mm;
    const [x, y] = part.plate_offset_mm;
    if (
      !finitePositive(sourceX)
      || !finitePositive(sourceY)
      || !finitePositive(sourceZ)
      || !finiteCoordinate(x)
      || !finiteCoordinate(y)
      || (part.plate_rotation_deg !== 0 && part.plate_rotation_deg !== 90)
    ) return false;
    const width = part.plate_rotation_deg === 90 ? sourceY : sourceX;
    const depth = part.plate_rotation_deg === 90 ? sourceX : sourceY;
    if (x + width > bedX + 0.001 || y + depth > bedY + 0.001 || sourceZ > bedZ + 0.001) {
      return false;
    }
    footprints.push({ x, y, width, depth });
  }
  for (const dowel of layout.dowels) {
    const [x, y] = dowel.plate_offset_mm;
    if (
      !finitePositive(dowel.diameter_mm)
      || !finitePositive(dowel.length_mm)
      || !finiteCoordinate(x)
      || !finiteCoordinate(y)
      || x + dowel.diameter_mm > bedX + 0.001
      || y + dowel.diameter_mm > bedY + 0.001
      || dowel.length_mm > bedZ + 0.001
    ) return false;
    footprints.push({ x, y, width: dowel.diameter_mm, depth: dowel.diameter_mm });
  }
  const edgeClearance = Math.min(...footprints.flatMap((shape) => [
    shape.x,
    shape.y,
    bedX - shape.x - shape.width,
    bedY - shape.y - shape.depth,
  ]));
  if (
    edgeClearance + 0.001 < requestedMarginMm
    || !finiteCoordinate(layout.minimum_edge_clearance_mm)
    || Math.abs(layout.minimum_edge_clearance_mm - edgeClearance) > 0.01
  ) return false;
  const separations: number[] = [];
  for (let leftIndex = 0; leftIndex < footprints.length; leftIndex += 1) {
    const left = footprints[leftIndex]!;
    for (let rightIndex = leftIndex + 1; rightIndex < footprints.length; rightIndex += 1) {
      const right = footprints[rightIndex]!;
      const separatedWithGap =
        left.x + left.width + requestedGapMm <= right.x + 0.001
        || right.x + right.width + requestedGapMm <= left.x + 0.001
        || left.y + left.depth + requestedGapMm <= right.y + 0.001
        || right.y + right.depth + requestedGapMm <= left.y + 0.001;
      if (!separatedWithGap) return false;
      const dx = Math.max(
        right.x - (left.x + left.width),
        left.x - (right.x + right.width),
        0,
      );
      const dy = Math.max(
        right.y - (left.y + left.depth),
        left.y - (right.y + right.depth),
        0,
      );
      separations.push(Math.hypot(dx, dy));
    }
  }
  if (separations.length > 0) {
    const minimumPartClearance = Math.min(...separations);
    if (
      !finiteCoordinate(layout.minimum_part_clearance_mm)
      || Math.abs(layout.minimum_part_clearance_mm - minimumPartClearance) > 0.01
    ) return false;
  }
  return footprints.length > 0;
}

/** Accept only an exact fit-to-bed draft produced for the selected immutable source. */
export function verifiedWebBuildPlateLayout(
  version: Version,
  sourceVersionId: string,
  requestedMarginMm: number,
  requestedGapMm: number,
): SplitProvenance | null {
  const provenance = version.provenance as {
    operation?: unknown;
    source_version_id?: unknown;
    split?: unknown;
  };
  const split = provenance.split as (SplitProvenance & { request?: unknown }) | undefined;
  const request = split?.request as {
    bed?: { x_mm?: unknown; y_mm?: unknown; z_mm?: unknown };
    margin_mm?: unknown;
    gap_mm?: unknown;
  } | undefined;
  if (
    version.state !== "draft"
    || version.parent_version_id !== sourceVersionId
    || provenance.operation !== "split_model"
    || provenance.source_version_id !== sourceVersionId
    || !split
    || !request?.bed
    || request.margin_mm !== requestedMarginMm
    || request.gap_mm !== requestedGapMm
    || !split.layout_bed_mm
    || request.bed.x_mm !== split.layout_bed_mm[0]
    || request.bed.y_mm !== split.layout_bed_mm[1]
    || request.bed.z_mm !== split.layout_bed_mm[2]
    || !validPlacementGeometry(split, requestedMarginMm, requestedGapMm)
    || !finiteCoordinate(split.minimum_edge_clearance_mm)
    || split.minimum_edge_clearance_mm + 0.001 < requestedMarginMm
  ) return null;

  const shapeCount = split.parts.length + split.dowels.length;
  if (
    shapeCount > 1
    && (!finiteCoordinate(split.minimum_part_clearance_mm)
      || split.minimum_part_clearance_mm + 0.001 < requestedGapMm)
  ) return null;
  const names = [...split.parts, ...split.dowels].map((item) => item.name);
  if (
    new Set(names).size !== names.length
    || split.parts.some((part) => part.fits_bed !== true || !part.asset_id)
    || split.dowels.some((dowel) => !dowel.asset_id)
  ) return null;
  return split;
}
