import type { FacadeCompatibility, Listing, Project } from "@physical-ai/contracts";

const SIZE_TOLERANCE_MM = 1;

function measuredSize(value: unknown): [number, number, number] | null {
  if (
    !Array.isArray(value)
    || value.length !== 3
    || value.some((item) => !Number.isFinite(item) || item <= 0)
  ) return null;
  return [value[0], value[1], value[2]];
}

function sameSize(left: number[], right: number[]): boolean {
  return left.length === 3 && right.length === 3
    && left.every((value, index) => value === right[index]);
}

/** Bind a pre-purchase envelope report to the exact selected project head and its own rows. */
export function verifiedFacadeCompatibility(
  report: FacadeCompatibility,
  project: Project | undefined,
  listing: Listing | null,
): FacadeCompatibility | null {
  if (
    !project?.head_version_id
    || !listing
    || report.project_id !== project.id
    || report.project_name !== project.name
    || report.version_id !== project.head_version_id
    || !Number.isInteger(report.total_openings)
    || !Number.isInteger(report.matched_openings)
    || report.total_openings !== report.openings.length
  ) return null;
  const members = new Map<string, { label: string; size: [number, number, number] }>();
  const memberVersionIds = new Set<string>([listing.version_id]);
  const anchorSize = measuredSize(listing.summary?.size_mm);
  if (anchorSize) members.set(listing.version_id, { label: listing.title, size: anchorSize });
  for (const component of listing.components ?? []) {
    const size = measuredSize(component.summary?.size_mm);
    if (memberVersionIds.has(component.version_id)) return null;
    memberVersionIds.add(component.version_id);
    if (size) members.set(component.version_id, { label: component.label, size });
  }
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
    const matchIds = new Set<string>();
    for (const match of opening.matches) {
      const member = members.get(match.version_id);
      const size = measuredSize(match.size_mm);
      if (
        !member
        || !size
        || matchIds.has(match.version_id)
        || match.label !== member.label
        || !sameSize(size, member.size)
      ) return null;
      matchIds.add(match.version_id);
      const [, first, second] = [...size].sort((left, right) => left - right);
      const wanted = [opening.width_mm, opening.height_mm].sort((left, right) => left - right);
      if (
        Math.abs(first - wanted[0]) > SIZE_TOLERANCE_MM
        || Math.abs(second - wanted[1]) > SIZE_TOLERANCE_MM
      ) return null;
    }
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
