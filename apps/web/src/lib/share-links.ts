export type SharedViewerFormat = "stl" | "glb";

/** The public viewer deliberately reuses only formats already parsed by ModelViewer.
 * Other viewer-safe assets remain downloadable instead of being fed to the wrong loader.
 */
export function sharedViewerFormat(format: string): SharedViewerFormat | null {
  const normalized = format.trim().toLowerCase();
  if (normalized === "stl") return "stl";
  if (normalized === "glb" || normalized === "gltf") return "glb";
  return null;
}
