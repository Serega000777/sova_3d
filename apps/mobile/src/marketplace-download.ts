import type { Download, MarketplaceFile } from "@physical-ai/contracts";

/** Return only a signed URL that still describes the exact buyer-authorized delivered file. */
export function verifiedMarketplaceDownloadUrl(
  file: MarketplaceFile,
  download: Download,
): string | null {
  if (
    download.asset_id !== file.asset_id
    || download.format !== file.format
    || download.byte_size !== file.byte_size
    || !Number.isInteger(download.expires_in_seconds)
    || download.expires_in_seconds <= 0
  ) return null;
  try {
    const url = new URL(download.url);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}
