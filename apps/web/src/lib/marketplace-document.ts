export const HOUSE_PDF_MIME = "application/pdf";
export const HOUSE_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/** Refuse an empty or mislabeled marketplace document before saving it under a trusted suffix. */
export function verifiedMarketplaceDocument(blob: Blob, expectedMime: string): Blob | null {
  const mime = blob.type.split(";", 1)[0]?.trim().toLowerCase();
  return blob.size > 0 && mime === expectedMime ? blob : null;
}
