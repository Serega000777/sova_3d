/** Deterministic guidance for the four-view object-photo workflow.
 *
 * A client cannot honestly infer which side of an unknown object it sees without a vision
 * model. The person therefore captures into explicit labelled slots. These checks cover
 * facts available locally before upload: completeness, resolution, encoded size, aspect
 * ratio, and exact duplicate selections.
 */

export const GUIDED_PHOTO_VIEWS = ["front", "right", "back", "left"] as const;
export type GuidedPhotoView = (typeof GUIDED_PHOTO_VIEWS)[number];

export type GuidedPhotoIssue =
  | "missing"
  | "low_resolution"
  | "file_too_small"
  | "extreme_aspect"
  | "duplicate";

export interface GuidedPhotoEvidence {
  view: GuidedPhotoView | null;
  width: number;
  height: number;
  byteSize?: number | null;
  fingerprint?: string | null;
}

export interface GuidedPhotoSlotAssessment {
  view: GuidedPhotoView;
  photoIndex: number | null;
  issues: GuidedPhotoIssue[];
  ready: boolean;
}

export interface GuidedPhotoAssessment {
  ready: boolean;
  slots: GuidedPhotoSlotAssessment[];
}

export function guidedPhotoViewLabel(view: GuidedPhotoView, language: "ru" | "en"): string {
  const labels = {
    front: { ru: "Спереди", en: "Front" },
    right: { ru: "Справа", en: "Right" },
    back: { ru: "Сзади", en: "Back" },
    left: { ru: "Слева", en: "Left" },
  } as const;
  return labels[view][language];
}

export function assessGuidedPhotos(photos: GuidedPhotoEvidence[]): GuidedPhotoAssessment {
  const duplicateFingerprints = new Set<string>();
  const seenFingerprints = new Set<string>();
  for (const photo of photos) {
    if (!photo.fingerprint) continue;
    if (seenFingerprints.has(photo.fingerprint)) duplicateFingerprints.add(photo.fingerprint);
    seenFingerprints.add(photo.fingerprint);
  }

  const slots = GUIDED_PHOTO_VIEWS.map((view): GuidedPhotoSlotAssessment => {
    const photoIndex = photos.findIndex((photo) => photo.view === view);
    if (photoIndex < 0) return { view, photoIndex: null, issues: ["missing"], ready: false };
    const photo = photos[photoIndex] as GuidedPhotoEvidence;
    const issues: GuidedPhotoIssue[] = [];
    const shortEdge = Math.min(photo.width, photo.height);
    const longEdge = Math.max(photo.width, photo.height);
    if (!Number.isFinite(shortEdge) || shortEdge < 720) issues.push("low_resolution");
    if (photo.byteSize != null && photo.byteSize < 40 * 1024) issues.push("file_too_small");
    if (shortEdge <= 0 || longEdge / shortEdge > 2) issues.push("extreme_aspect");
    if (photo.fingerprint && duplicateFingerprints.has(photo.fingerprint)) issues.push("duplicate");
    return { view, photoIndex, issues, ready: issues.length === 0 };
  });
  return { ready: slots.every((slot) => slot.ready), slots };
}
