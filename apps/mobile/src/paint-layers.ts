export interface PaintLayerSummary {
  name: string;
  strokeCount: number;
  colours: string[];
  materialIds: string[];
  opacities: number[];
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

export function paintLayerSummaries(
  provenance: Record<string, unknown> | null | undefined,
  sceneNodeId: string | null = null,
): PaintLayerSummary[] {
  const scenePaint = record(provenance?.scene_paint);
  const paint = sceneNodeId ? record(scenePaint?.[sceneNodeId]) : record(provenance?.paint);
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
    const surfaces = layerStrokes.map((stroke) => {
      const value = record(stroke);
      const colour = value?.colour;
      const materialId = value?.catalog_material_id;
      const customAssetId = value?.custom_texture_asset_id;
      const customTileSize = value?.custom_texture_tile_size_mm;
      const customRoughness = value?.custom_texture_roughness;
      const customMetallic = value?.custom_texture_metallic;
      const validColour = typeof colour === "string" && /^#[0-9a-f]{6}$/i.test(colour);
      const validMaterial = typeof materialId === "string" && materialId.length >= 1 && materialId.length <= 120;
      const validCustom = typeof customAssetId === "string"
        && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(customAssetId)
        && typeof customTileSize === "number" && customTileSize >= 10 && customTileSize <= 5000
        && typeof customRoughness === "number" && customRoughness >= 0.04 && customRoughness <= 1
        && typeof customMetallic === "number" && customMetallic >= 0 && customMetallic <= 1;
      return Number(validColour) + Number(validMaterial) + Number(validCustom) === 1
        ? {
            colour: validColour ? colour : null,
            materialId: validMaterial
              ? materialId
              : validCustom ? `workspace.texture.${customAssetId}` : null,
          }
        : null;
    });
    if (surfaces.some((surface) => surface === null)) return [];
    const colours = [...new Set(surfaces.flatMap((surface) => surface?.colour ? [surface.colour] : []))];
    const materialIds = [...new Set(surfaces.flatMap((surface) => surface?.materialId ? [surface.materialId] : []))];
    const opacityValues = layerStrokes.map((stroke) => {
      const opacity = record(stroke)?.opacity;
      if (opacity === undefined) return 1;
      return typeof opacity === "number" && Number.isFinite(opacity) && opacity >= 0.05 && opacity <= 1
        ? opacity
        : null;
    });
    if (opacityValues.some((opacity) => opacity === null)) return [];
    const opacities = [...new Set(opacityValues as number[])];
    return [{ name, strokeCount: count as number, colours, materialIds, opacities }];
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
