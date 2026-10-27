import type { Scan, Version } from "@physical-ai/contracts";

export function acceptedScanResults(scans: readonly Scan[]): Map<string, Scan> {
  return new Map(
    scans
      .filter((scan): scan is Scan & { result_version_id: string } => (
        scan.status === "accepted" && typeof scan.result_version_id === "string"
      ))
      .map((scan) => [scan.result_version_id, scan]),
  );
}

export function physicalComparisonModelAsset(
  version: Pick<Version, "assets">,
): { assetId: string; format: "stl" | "glb" } | null {
  const preview = version.assets.find((asset) => asset.role === "preview");
  if (preview) return { assetId: preview.asset_id, format: "glb" };
  const model = version.assets.find((asset) => asset.role === "model")
    ?? version.assets.find((asset) => asset.role === "scan");
  return model ? { assetId: model.asset_id, format: "stl" } : null;
}
