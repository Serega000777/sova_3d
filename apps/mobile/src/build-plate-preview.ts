import type { SplitProvenance, Version } from "@physical-ai/contracts";

export interface BuildPlateShape {
  id: string;
  kind: "part" | "dowel";
  label: string;
  leftPct: number;
  bottomPct: number;
  widthPct: number;
  heightPct: number;
}

export interface BuildPlatePreviewModel {
  bedX: number;
  bedY: number;
  shapes: BuildPlateShape[];
}

function finitePositive(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function finiteCoordinate(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

export function buildPlatePreviewModel(
  layout: SplitProvenance,
): BuildPlatePreviewModel | null {
  const bed = layout.layout_bed_mm;
  if (!bed || !finitePositive(bed[0]) || !finitePositive(bed[1]) || !finitePositive(bed[2])) return null;
  const [bedX, bedY, bedZ] = bed;
  const shapes: BuildPlateShape[] = [];

  for (const [index, part] of layout.parts.entries()) {
    const [sourceX, sourceY, sourceZ] = part.extents_mm;
    const [x, y] = part.plate_offset_mm;
    if (
      !finitePositive(sourceX) ||
      !finitePositive(sourceY) ||
      !finitePositive(sourceZ) ||
      !finiteCoordinate(x) ||
      !finiteCoordinate(y) ||
      (part.plate_rotation_deg !== 0 && part.plate_rotation_deg !== 90)
    ) return null;
    const width = part.plate_rotation_deg === 90 ? sourceY : sourceX;
    const height = part.plate_rotation_deg === 90 ? sourceX : sourceY;
    if (x + width > bedX + 0.001 || y + height > bedY + 0.001 || sourceZ > bedZ + 0.001) return null;
    shapes.push({
      id: part.name,
      kind: "part",
      label: `${index + 1} · ${part.plate_rotation_deg}°`,
      leftPct: x / bedX * 100,
      bottomPct: y / bedY * 100,
      widthPct: width / bedX * 100,
      heightPct: height / bedY * 100,
    });
  }

  for (const [index, dowel] of layout.dowels.entries()) {
    const [x, y] = dowel.plate_offset_mm ?? [];
    const diameter = dowel.diameter_mm;
    if (!finitePositive(diameter) || !finiteCoordinate(x) || !finiteCoordinate(y)) return null;
    if (x + diameter > bedX + 0.001 || y + diameter > bedY + 0.001) return null;
    shapes.push({
      id: dowel.name,
      kind: "dowel",
      label: `D${index + 1}`,
      leftPct: x / bedX * 100,
      bottomPct: y / bedY * 100,
      widthPct: diameter / bedX * 100,
      heightPct: diameter / bedY * 100,
    });
  }
  return shapes.length > 0 ? { bedX, bedY, shapes } : null;
}

/** Accept only the exact fit-to-bed draft produced for the selected immutable source. */
export function verifiedBuildPlateLayout(
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
    || !buildPlatePreviewModel(split)
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
