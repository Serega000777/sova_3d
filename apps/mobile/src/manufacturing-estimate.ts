import type { Job, ManufacturingEstimate as SavedEstimate, PrintAnalysis } from "@physical-ai/contracts";

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

export interface ManufacturingEstimateInput {
  machine_rate_per_hour: number | null;
  printer_power_w: number | null;
  electricity_rate_per_kwh: number | null;
  postprocess_hours: number | null;
  postprocess_rate_per_hour: number | null;
}

export interface RestoredManufacturingEstimate {
  input: ManufacturingEstimateInput;
  total: number;
  createdAt: string;
}

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

/** Accept only the persisted record named by this exact terminal analysis job. */
export function verifiedPrintAnalysisJob(
  job: Job,
  analyses: readonly PrintAnalysis[],
  versionId: string,
  printerProfileId: string,
  materialId: string,
): PrintAnalysis | null {
  if (
    job.type !== "analyze_print"
    || job.status !== "succeeded"
    || job.project_version_id !== versionId
  ) return null;
  const result = job.result as { analysis_id?: unknown; kind?: unknown } | null;
  if (typeof result?.analysis_id !== "string" || result.kind !== "analysis") return null;
  const analysis = analyses.find((candidate) => candidate.id === result.analysis_id) ?? null;
  return analysisMatchesManufacturingContext(
    analysis,
    versionId,
    printerProfileId,
    materialId,
  ) ? analysis : null;
}

function optionalNumber(text: string, maximum: number): number | null | undefined {
  const normalized = text.trim().replace(",", ".");
  if (!normalized) return null;
  const value = Number(normalized);
  return Number.isFinite(value) && value >= 0 && value <= maximum
    ? Math.round((value + Number.EPSILON) * 10_000) / 10_000
    : undefined;
}

export function manufacturingEstimateInput(
  draft: Pick<
    ManufacturingEstimateDraft,
    | "machineHourlyText"
    | "printerPowerWText"
    | "electricityPerKwhText"
    | "postProcessHoursText"
    | "postProcessHourlyText"
  >,
): ManufacturingEstimateInput | null {
  const machine = optionalNumber(draft.machineHourlyText, 1_000_000);
  const power = optionalNumber(draft.printerPowerWText, 100_000);
  const electricity = optionalNumber(draft.electricityPerKwhText, 1_000_000);
  const postHours = optionalNumber(draft.postProcessHoursText, 10_000);
  const postRate = optionalNumber(draft.postProcessHourlyText, 1_000_000);
  if ([machine, power, electricity, postHours, postRate].includes(undefined)) return null;
  if ((power === null) !== (electricity === null)) return null;
  if ((postHours === null) !== (postRate === null)) return null;
  return {
    machine_rate_per_hour: machine!,
    printer_power_w: power!,
    electricity_rate_per_kwh: electricity!,
    postprocess_hours: postHours!,
    postprocess_rate_per_hour: postRate!,
  };
}

function finiteApiNumber(value: unknown, maximum: number): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 && parsed <= maximum ? parsed : null;
}

/** Restore only a server snapshot that still matches the exact analysis and recomputed totals. */
export function restoredManufacturingEstimate(
  saved: SavedEstimate,
  analysis: PrintAnalysis,
  versionId: string,
  printerProfileId: string,
  materialId: string,
): RestoredManufacturingEstimate | null {
  if (
    saved.analysis_id !== analysis.id
    || saved.project_version_id !== versionId
    || analysis.project_version_id !== versionId
    || (saved.printer_profile_id ?? "") !== printerProfileId
    || (analysis.printer_profile_id ?? "") !== printerProfileId
    || saved.material_id !== materialId
    || analysis.material_id !== materialId
    || !/^[A-Za-z]{3}$/.test(saved.currency)
    || !Number.isFinite(Date.parse(saved.created_at))
  ) return null;
  const metrics = (analysis.report as { metrics?: Record<string, unknown> } | null)?.metrics;
  const materialTotal = finiteApiNumber(metrics?.total_cost, 1_000_000_000_000);
  const printTimeMin = finiteApiNumber(metrics?.print_time_min, 10_000_000);
  const savedMaterial = finiteApiNumber(saved.material_cost, 1_000_000_000_000);
  const savedTime = finiteApiNumber(saved.print_time_min, 10_000_000);
  const savedTotal = finiteApiNumber(saved.total_cost, 99_999_999_999_999.99);
  if (
    materialTotal === null
    || printTimeMin === null
    || savedMaterial === null
    || savedTime === null
    || savedTotal === null
    || Math.abs(materialTotal - savedMaterial) > 0.0001
    || Math.abs(printTimeMin - savedTime) > 0.0001
  ) return null;
  const values = {
    machine_rate_per_hour: finiteApiNumber(saved.machine_rate_per_hour, 1_000_000),
    printer_power_w: finiteApiNumber(saved.printer_power_w, 100_000),
    electricity_rate_per_kwh: finiteApiNumber(saved.electricity_rate_per_kwh, 1_000_000),
    postprocess_hours: finiteApiNumber(saved.postprocess_hours, 10_000),
    postprocess_rate_per_hour: finiteApiNumber(saved.postprocess_rate_per_hour, 1_000_000),
  };
  for (const [key, raw] of Object.entries({
    machine_rate_per_hour: saved.machine_rate_per_hour,
    printer_power_w: saved.printer_power_w,
    electricity_rate_per_kwh: saved.electricity_rate_per_kwh,
    postprocess_hours: saved.postprocess_hours,
    postprocess_rate_per_hour: saved.postprocess_rate_per_hour,
  })) {
    if (raw != null && values[key as keyof typeof values] === null) return null;
  }
  if ((values.printer_power_w === null) !== (values.electricity_rate_per_kwh === null)) return null;
  if ((values.postprocess_hours === null) !== (values.postprocess_rate_per_hour === null)) return null;
  const recomputed = calculateManufacturingEstimate({
    materialTotal: savedMaterial,
    printTimeMin: savedTime,
    machineHourlyText: values.machine_rate_per_hour?.toString() ?? "",
    printerPowerWText: values.printer_power_w?.toString() ?? "",
    electricityPerKwhText: values.electricity_rate_per_kwh?.toString() ?? "",
    postProcessHoursText: values.postprocess_hours?.toString() ?? "",
    postProcessHourlyText: values.postprocess_rate_per_hour?.toString() ?? "",
  });
  const storedComponents = [saved.machine_cost, saved.electricity_cost, saved.postprocess_cost]
    .map((value) => finiteApiNumber(value, 99_999_999_999_999.99));
  if (
    !recomputed.valid
    || storedComponents.some((value) => value === null)
    || Math.abs(recomputed.machineCost - storedComponents[0]!) > 0.011
    || Math.abs(recomputed.electricityCost - storedComponents[1]!) > 0.011
    || Math.abs(recomputed.postProcessCost - storedComponents[2]!) > 0.011
    || Math.abs(recomputed.total - savedTotal) > 0.011
  ) return null;
  return { input: values, total: savedTotal, createdAt: saved.created_at };
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
