export interface VersionAssetLink {
  asset_id: string;
  role: string;
}

/** A direct open action is safe only when the immutable version has one scan source. */
export function singleVersionScanAssetId(assets: VersionAssetLink[]): string | null {
  const ids = new Set(
    assets
      .filter((asset) => asset.role === "scan" && asset.asset_id)
      .map((asset) => asset.asset_id),
  );
  return ids.size === 1 ? [...ids][0] ?? null : null;
}
