import type { SplitProvenance } from "@physical-ai/contracts";

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
  if (!bed || !finitePositive(bed[0]) || !finitePositive(bed[1])) return null;
  const [bedX, bedY] = bed;
  const shapes: BuildPlateShape[] = [];

  for (const [index, part] of layout.parts.entries()) {
    const [sourceX, sourceY] = part.extents_mm;
    const [x, y] = part.plate_offset_mm;
    if (
      !finitePositive(sourceX) ||
      !finitePositive(sourceY) ||
      !finiteCoordinate(x) ||
      !finiteCoordinate(y) ||
      (part.plate_rotation_deg !== 0 && part.plate_rotation_deg !== 90)
    ) return null;
    const width = part.plate_rotation_deg === 90 ? sourceY : sourceX;
    const height = part.plate_rotation_deg === 90 ? sourceX : sourceY;
    if (x + width > bedX + 0.001 || y + height > bedY + 0.001) return null;
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
