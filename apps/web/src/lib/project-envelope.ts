import type { ProjectSummary } from "@physical-ai/contracts";

export type ProjectEnvelope = readonly [number, number, number];

export function projectEnvelope(project: ProjectSummary): ProjectEnvelope | null {
  const provenance = project.head_version?.provenance;
  const bodies = provenance && Array.isArray(provenance.bodies) ? provenance.bodies : [];
  const body = bodies.at(-1);
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const record = body as Record<string, unknown>;
  if (record.valid !== true) return null;
  const bbox = record.bbox_mm;
  if (!bbox || typeof bbox !== "object" || Array.isArray(bbox)) return null;
  const size = (bbox as Record<string, unknown>).size;
  if (!Array.isArray(size) || size.length !== 3) return null;
  const values = size.map(Number);
  if (values.some((value) => !Number.isFinite(value) || value <= 0 || value > 1_000_000)) {
    return null;
  }
  return values as [number, number, number];
}
