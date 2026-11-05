import type {
  Job,
  PrintDiagnosis,
  PrintSymptom,
} from "@physical-ai/contracts";

const SYMPTOMS = new Set<PrintSymptom>([
  "stringing",
  "warping",
  "poor_adhesion",
  "elephant_foot",
  "under_extrusion",
  "over_extrusion",
  "poor_overhangs",
  "layer_shift",
  "dimensions_off",
  "clogging",
]);

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function finiteRecord(value: unknown): Record<string, number> | null {
  const raw = record(value);
  if (!raw) return null;
  const result: Record<string, number> = {};
  for (const [key, item] of Object.entries(raw)) {
    if (!key || typeof item !== "number" || !Number.isFinite(item)) return null;
    result[key] = item;
  }
  return result;
}

/** Runtime validation for both direct rule results and asynchronous vision-job results. */
export function parsePrintDiagnosis(
  value: unknown,
  expectedMaterialId: string,
  expectedApplied: boolean,
): PrintDiagnosis | null {
  const raw = record(value);
  if (
    !raw
    || raw.material_id !== expectedMaterialId
    || !["success", "partial", "failed"].includes(String(raw.outcome))
    || raw.applied !== expectedApplied
    || !Number.isInteger(raw.reports)
    || Number(raw.reports) < 0
    || !Array.isArray(raw.findings)
  ) return null;
  const tuning = finiteRecord(raw.tuning);
  if (!tuning) return null;
  const findings: PrintDiagnosis["findings"] = [];
  for (const value of raw.findings) {
    const finding = record(value);
    if (
      !finding
      || typeof finding.symptom !== "string"
      || !SYMPTOMS.has(finding.symptom as PrintSymptom)
      || !Array.isArray(finding.causes)
      || finding.causes.some((cause) => typeof cause !== "string" || !cause.trim())
      || !Array.isArray(finding.changes)
      || typeof finding.advice !== "string"
    ) return null;
    const changes: PrintDiagnosis["findings"][number]["changes"] = [];
    for (const value of finding.changes) {
      const change = record(value);
      if (
        !change
        || typeof change.setting !== "string"
        || !change.setting.trim()
        || typeof change.before !== "number"
        || !Number.isFinite(change.before)
        || typeof change.after !== "number"
        || !Number.isFinite(change.after)
      ) return null;
      changes.push({ setting: change.setting, before: change.before, after: change.after });
    }
    findings.push({
      symptom: finding.symptom as PrintSymptom,
      causes: finding.causes as string[],
      changes,
      advice: finding.advice,
    });
  }
  return {
    material_id: expectedMaterialId,
    outcome: raw.outcome as PrintDiagnosis["outcome"],
    findings,
    tuning,
    applied: expectedApplied,
    reports: Number(raw.reports),
  };
}

export function verifiedPhotoDiagnosisJob(
  job: Job,
  workspaceId: string,
  materialId: string,
): PrintDiagnosis | null {
  if (job.type !== "diagnose_print_photo" || job.workspace_id !== workspaceId || job.status !== "succeeded") {
    return null;
  }
  return parsePrintDiagnosis(job.result, materialId, false);
}

export function photoDiagnosisEvidence(value: unknown): { symptom: PrintSymptom; evidence: string; confidence: number }[] {
  const raw = record(value);
  const photo = record(raw?.photo);
  if (!Array.isArray(photo?.seen)) return [];
  return photo.seen.flatMap((value) => {
    const item = record(value);
    return item
      && typeof item.symptom === "string"
      && SYMPTOMS.has(item.symptom as PrintSymptom)
      && typeof item.evidence === "string"
      && item.evidence.trim()
      && typeof item.confidence === "number"
      && Number.isFinite(item.confidence)
      && item.confidence >= 0.5
      && item.confidence <= 1
      ? [{
          symptom: item.symptom as PrintSymptom,
          evidence: item.evidence,
          confidence: item.confidence,
        }]
      : [];
  });
}
