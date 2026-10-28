export interface PaintLayerSummary {
  name: string;
  strokeCount: number;
  colours: string[];
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

export function paintLayerSummaries(provenance: Record<string, unknown> | null | undefined): PaintLayerSummary[] {
  const paint = record(provenance?.paint);
  const strokes = Array.isArray(paint?.strokes) ? paint.strokes : null;
  const layers = Array.isArray(paint?.layers) ? paint.layers : null;
  if (!strokes || !layers) return [];

  return layers.flatMap((value) => {
    const layer = record(value);
    const name = typeof layer?.name === "string" ? layer.name.trim() : "";
    const start = layer?.stroke_start;
    const count = layer?.stroke_count;
    if (
      !name
      || name.length > 80
      || !Number.isInteger(start)
      || !Number.isInteger(count)
      || (start as number) < 0
      || (count as number) < 1
      || (start as number) + (count as number) > strokes.length
    ) return [];
    const colours = [...new Set(
      strokes
        .slice(start as number, (start as number) + (count as number))
        .map((stroke) => record(stroke)?.colour)
        .filter((colour): colour is string => typeof colour === "string" && /^#[0-9a-f]{6}$/i.test(colour)),
    )];
    return [{ name, strokeCount: count as number, colours }];
  });
}
