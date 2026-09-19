/** F-019: a phone photo is 3–8 MB; the planner needs the object, not the megapixels. */
export const PHOTO_MAX_EDGE_PX = 1600;

/** Re-encode a photo as a JPEG no larger than `maxEdge` on its long side (EXIF applied). */
export async function shrinkPhoto(file: Blob, maxEdge = PHOTO_MAX_EDGE_PX): Promise<Blob> {
  if (typeof createImageBitmap !== "function") return file;
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  const context = canvas.getContext("2d");
  if (!context) return file;
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return new Promise((resolve) =>
    canvas.toBlob((blob) => resolve(blob ?? file), "image/jpeg", 0.85),
  );
}

/** What the version's provenance says about how a photo-built model was sized. */
export function describeScale(
  scale: { source: string; confidence: string; basis?: string } | null | undefined,
): string | null {
  if (!scale) return null;
  const source =
    scale.source === "user"
      ? "your text"
      : scale.source === "reference_object"
        ? "a reference object in the photo"
        : "an estimate";
  return `Size from ${source} (${scale.confidence} confidence${scale.basis ? `: ${scale.basis}` : ""})`;
}
