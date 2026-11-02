export interface PaintLayerSummary {
  name: string;
  strokeCount: number;
  colours: string[];
  opacities: number[];
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
    const layerStrokes = strokes.slice(start as number, (start as number) + (count as number));
    const colours = [...new Set(
      layerStrokes
        .map((stroke) => record(stroke)?.colour)
        .filter((colour): colour is string => typeof colour === "string" && /^#[0-9a-f]{6}$/i.test(colour)),
    )];
    const opacityValues = layerStrokes.map((stroke) => {
      const opacity = record(stroke)?.opacity;
      if (opacity === undefined) return 1;
      return typeof opacity === "number" && Number.isFinite(opacity) && opacity >= 0.05 && opacity <= 1
        ? opacity
        : null;
    });
    if (opacityValues.some((opacity) => opacity === null)) return [];
    const opacities = [...new Set(opacityValues as number[])];
    return [{ name, strokeCount: count as number, colours, opacities }];
  });
}

export function movePaintLayerOrder(
  layers: readonly PaintLayerSummary[],
  index: number,
  direction: -1 | 1,
): string[] | null {
  const names = layers.map((layer) => layer.name);
  if (names.length < 2 || new Set(names).size !== names.length) return null;
  const target = index + direction;
  if (!Number.isInteger(index) || index < 0 || target < 0 || target >= names.length) return null;
  [names[index], names[target]] = [names[target]!, names[index]!];
  return names;
}
