import type { Download } from "@physical-ai/contracts";

export interface MarketplaceModelPreview {
  url: string;
  format: "stl" | "glb";
}

/** Accept only the exact listed asset in a format the native Three.js viewer can load. */
export function verifiedMarketplaceModelPreview(
  expectedAssetId: string,
  download: Download,
): MarketplaceModelPreview | null {
  if (
    download.asset_id !== expectedAssetId
    || !Number.isInteger(download.byte_size)
    || download.byte_size <= 0
    || !Number.isInteger(download.expires_in_seconds)
    || download.expires_in_seconds <= 0
  ) return null;
  const format = download.format?.toLowerCase();
  if (format !== "stl" && format !== "glb") return null;
  try {
    const url = new URL(download.url);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    return { url: url.toString(), format };
  } catch {
    return null;
  }
}
