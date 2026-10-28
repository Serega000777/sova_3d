import type { InteriorMaterial, SceneGraph } from "@physical-ai/contracts";

/** A material mutation is accepted only when the returned immutable child contains the exact
 * requested catalogue snapshot on exactly the requested visible object. */
export function interiorMaterialResultMatches(
  scene: SceneGraph,
  sourceVersionId: string,
  sceneNodeId: string,
  material: InteriorMaterial | null,
): boolean {
  if (scene.parent_version_id !== sourceVersionId || scene.version_id === sourceVersionId) {
    return false;
  }
  const matches = scene.nodes.filter((node) => node.id === sceneNodeId);
  if (matches.length !== 1) return false;
  const node = matches[0]!;
  if (node.kind !== "object" || !node.effective_visible) return false;
  if (material === null) return node.appearance == null;
  const appearance = node.appearance;
  return Boolean(
    appearance
    && appearance.schema_version === 1
    && appearance.catalog_material_id === material.id
    && appearance.name === material.name
    && appearance.name_ru === material.name_ru
    && appearance.base_color === material.base_color
    && appearance.gloss_pct === material.gloss_pct
    && appearance.roughness === material.roughness
    && appearance.texture_sha256 === material.texture_sha256
    && appearance.texture_tile_size_mm === material.texture_tile_size_mm
    && appearance.texture_url === material.texture_url
  );
}
