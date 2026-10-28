export interface ManufacturingEstimateDraft {
  materialTotal: number;
  printTimeMin: number;
  machineHourlyText: string;
  printerPowerWText: string;
  electricityPerKwhText: string;
  postProcessHoursText: string;
  postProcessHourlyText: string;
}

export type ManufacturingEstimate =
  | {
      valid: true;
      machineCost: number;
      electricityCost: number;
      postProcessCost: number;
      total: number;
    }
  | { valid: false; error: "invalid_value" | "incomplete_electricity" | "incomplete_post_process" };

/** A saved print analysis is usable as an estimate only for the controls that produced it. */
export function analysisMatchesManufacturingContext(
  analysis: PrintAnalysis | null,
  versionId: string | null,
  printerProfileId: string,
  materialId: string,
): boolean {
  return Boolean(
    analysis
    && versionId
    && analysis.kind === "analysis"
    && analysis.project_version_id === versionId
    && (analysis.printer_profile_id ?? "") === printerProfileId
    && (analysis.material_id ?? "") === materialId,
  );
}

function optionalNumber(text: string, maximum: number): number | null | undefined {
  const normalized = text.trim().replace(",", ".");
  if (!normalized) return null;
  const value = Number(normalized);
  return Number.isFinite(value) && value >= 0 && value <= maximum ? value : undefined;
}

export function calculateManufacturingEstimate(
  draft: ManufacturingEstimateDraft,
): ManufacturingEstimate {
  if (
    !Number.isFinite(draft.materialTotal) ||
    draft.materialTotal < 0 ||
    !Number.isFinite(draft.printTimeMin) ||
    draft.printTimeMin < 0
  ) {
    return { valid: false, error: "invalid_value" };
  }
  const machineHourly = optionalNumber(draft.machineHourlyText, 1_000_000);
  const printerPowerW = optionalNumber(draft.printerPowerWText, 100_000);
  const electricityPerKwh = optionalNumber(draft.electricityPerKwhText, 1_000_000);
  const postProcessHours = optionalNumber(draft.postProcessHoursText, 10_000);
  const postProcessHourly = optionalNumber(draft.postProcessHourlyText, 1_000_000);
  if (
    machineHourly === undefined ||
    printerPowerW === undefined ||
    electricityPerKwh === undefined ||
    postProcessHours === undefined ||
    postProcessHourly === undefined
  ) {
    return { valid: false, error: "invalid_value" };
  }
  if ((printerPowerW === null) !== (electricityPerKwh === null)) {
    return { valid: false, error: "incomplete_electricity" };
  }
  if ((postProcessHours === null) !== (postProcessHourly === null)) {
    return { valid: false, error: "incomplete_post_process" };
  }

  const printHours = draft.printTimeMin / 60;
  const money = (value: number) => Math.round((value + Number.EPSILON) * 100) / 100;
  const machineCost = money(printHours * (machineHourly ?? 0));
  const electricityCost = money(
    printHours * ((printerPowerW ?? 0) / 1000) * (electricityPerKwh ?? 0),
  );
  const postProcessCost = money((postProcessHours ?? 0) * (postProcessHourly ?? 0));
  const total = money(draft.materialTotal + machineCost + electricityCost + postProcessCost);
  if (![machineCost, electricityCost, postProcessCost, total].every(Number.isFinite)) {
    return { valid: false, error: "invalid_value" };
  }
  return { valid: true, machineCost, electricityCost, postProcessCost, total };
}
import type { PrintAnalysis } from "@physical-ai/contracts";
