export interface VersionAssetLink {
  asset_id: string;
  role: string;
  thumbnail_angle?: string | null;
}

export interface VersionAssetGroup {
  role: string;
  assetCount: number;
  thumbnailAngles: string[];
}

const ROLE_ORDER = ["model", "source", "export", "scan", "room_shell", "preview", "thumbnail"];

/** Group only persisted version-asset links; one content asset is counted once per role. */
export function groupVersionAssets(assets: VersionAssetLink[]): VersionAssetGroup[] {
  const groups = new Map<string, { ids: Set<string>; angles: Set<string> }>();
  for (const asset of assets) {
    if (!asset.asset_id || !asset.role) continue;
    const group = groups.get(asset.role) ?? { ids: new Set<string>(), angles: new Set<string>() };
    group.ids.add(asset.asset_id);
    if (asset.thumbnail_angle) group.angles.add(asset.thumbnail_angle);
    groups.set(asset.role, group);
  }
  return [...groups.entries()]
    .sort(([left], [right]) => {
      const leftIndex = ROLE_ORDER.indexOf(left);
      const rightIndex = ROLE_ORDER.indexOf(right);
      return (leftIndex < 0 ? ROLE_ORDER.length : leftIndex)
        - (rightIndex < 0 ? ROLE_ORDER.length : rightIndex)
        || left.localeCompare(right);
    })
    .map(([role, group]) => ({
      role,
      assetCount: group.ids.size,
      thumbnailAngles: [...group.angles].sort(),
    }));
}

export function uniqueVersionAssetCount(assets: VersionAssetLink[]): number {
  return new Set(assets.map((asset) => asset.asset_id).filter(Boolean)).size;
}

export function versionAssetRoleLabel(role: string, ru: boolean): string {
  const labels: Record<string, [string, string]> = {
    model: ["3D-модель", "3D model"],
    source: ["Исходник", "Source"],
    export: ["Экспорт", "Export"],
    scan: ["Скан", "Scan"],
    room_shell: ["Оболочка комнаты", "Room shell"],
    preview: ["Превью", "Preview"],
    thumbnail: ["Ракурсы", "Views"],
  };
  return labels[role]?.[ru ? 0 : 1] ?? role;
}
