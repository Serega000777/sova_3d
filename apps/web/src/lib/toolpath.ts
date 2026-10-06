/** Parse the slicer's machine-ready G-code into a complete, layer-by-layer preview. */

export type ToolpathKind =
  | "perimeter"
  | "solid-infill"
  | "infill"
  | "support"
  | "support-interface"
  | "skirt"
  | "brim"
  | "travel"
  | "unknown";

export interface ToolpathSegment {
  from: [number, number];
  to: [number, number];
  kind: ToolpathKind;
}

export interface ToolpathLayer {
  index: number;
  z_mm: number;
  segments: ToolpathSegment[];
}

export interface ToolpathPreview {
  layers: ToolpathLayer[];
  bounds: { min: [number, number]; max: [number, number] };
  segment_count: number;
}

const KINDS = new Set<ToolpathKind>([
  "perimeter",
  "solid-infill",
  "infill",
  "support",
  "support-interface",
  "skirt",
  "brim",
]);

function value(line: string, letter: string): number | null {
  const match = line.match(new RegExp(`(?:^|\\s)${letter}(-?\\d+(?:\\.\\d+)?)`));
  return match ? Number(match[1]) : null;
}

export function parseToolpath(gcode: string): ToolpathPreview {
  const layers: ToolpathLayer[] = [];
  let layer: ToolpathLayer | null = null;
  const beforeFirstLayer: ToolpathSegment[] = [];
  let kind: ToolpathKind = "unknown";
  let x: number | null = null;
  let y: number | null = null;
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  let segmentCount = 0;

  for (const raw of gcode.split(/\r?\n/)) {
    const line = raw.trim();
    const layerMatch = line.match(/^;\s*layer\s+(\d+)\/\d+\s+z=(-?\d+(?:\.\d+)?)/i);
    if (layerMatch) {
      layer = { index: Number(layerMatch[1]), z_mm: Number(layerMatch[2]), segments: [] };
      if (layers.length === 0 && beforeFirstLayer.length) layer.segments.push(...beforeFirstLayer);
      layers.push(layer);
      kind = "unknown";
      continue;
    }
    const typeMatch = line.match(/^;\s*TYPE:([a-z-]+)/i);
    if (typeMatch) {
      const candidate = typeMatch[1].toLowerCase() as ToolpathKind;
      kind = KINDS.has(candidate) ? candidate : "unknown";
      continue;
    }
    if (!line.startsWith("G0") && !line.startsWith("G1")) continue;
    const nextX = value(line, "X");
    const nextY = value(line, "Y");
    if (nextX === null && nextY === null) continue;
    const toX: number | null = nextX ?? x;
    const toY: number | null = nextY ?? y;
    if (x !== null && y !== null && toX !== null && toY !== null) {
      const extrusion = value(line, "E");
      const segmentKind = extrusion !== null && extrusion > 0 ? kind : "travel";
      const segment = { from: [x, y], to: [toX, toY], kind: segmentKind } as ToolpathSegment;
      if (layer) layer.segments.push(segment);
      else if (segmentKind !== "travel") beforeFirstLayer.push(segment);
      if (layer || segmentKind !== "travel") {
        minX = Math.min(minX, x, toX);
        minY = Math.min(minY, y, toY);
        maxX = Math.max(maxX, x, toX);
        maxY = Math.max(maxY, y, toY);
        segmentCount += 1;
      }
    }
    x = toX;
    y = toY;
  }

  if (!Number.isFinite(minX)) minX = minY = maxX = maxY = 0;
  return {
    layers,
    bounds: { min: [minX, minY], max: [maxX, maxY] },
    segment_count: segmentCount,
  };
}

export const TOOLPATH_COLOURS: Record<ToolpathKind, string> = {
  perimeter: "#71a8ff",
  "solid-infill": "#d091ff",
  infill: "#61d7b8",
  support: "#ffb55f",
  "support-interface": "#ff7c67",
  skirt: "#99a4b7",
  brim: "#d5d9e2",
  travel: "#596579",
  unknown: "#ffffff",
};
