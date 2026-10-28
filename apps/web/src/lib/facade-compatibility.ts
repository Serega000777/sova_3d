import type { FacadeCompatibility, Project } from "@physical-ai/contracts";

/** Bind a pre-purchase envelope report to the exact selected project head and its own rows. */
export function verifiedFacadeCompatibility(
  report: FacadeCompatibility,
  project: Project | undefined,
): FacadeCompatibility | null {
  if (
    !project?.head_version_id
    || report.project_id !== project.id
    || report.version_id !== project.head_version_id
    || !Number.isInteger(report.total_openings)
    || !Number.isInteger(report.matched_openings)
    || report.total_openings !== report.openings.length
  ) return null;
  const ids = new Set<string>();
  for (const opening of report.openings) {
    if (
      !opening.opening_id
      || ids.has(opening.opening_id)
      || !Number.isFinite(opening.width_mm)
      || opening.width_mm <= 0
      || !Number.isFinite(opening.height_mm)
      || opening.height_mm <= 0
      || !Array.isArray(opening.matches)
    ) return null;
    ids.add(opening.opening_id);
  }
  const matched = report.openings.filter((opening) => opening.matches.length > 0).length;
  if (report.matched_openings !== matched) return null;
  const expectedStatus = report.openings.length === 0
    ? "unsupported"
    : matched === report.openings.length
      ? "complete"
      : matched > 0
        ? "partial"
        : "incompatible";
  return report.status === expectedStatus ? report : null;
}
