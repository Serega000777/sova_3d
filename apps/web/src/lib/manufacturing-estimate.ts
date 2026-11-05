import type {
  ManufacturingEstimate,
  PrintAnalysis,
  Schemas,
} from "@physical-ai/contracts";

export interface ManufacturingMetrics {
  mass_g?: number | null;
  support_mass_g?: number | null;
  layers?: number | null;
  print_time_min: number;
  material_cost?: number | null;
  support_cost?: number | null;
  total_cost: number;
  currency: string;
}

export interface ManufacturingRateDraft {
  machineRatePerHour: string;
  printerPowerW: string;
  electricityRatePerKwh: string;
  postprocessHours: string;
  postprocessRatePerHour: string;
}

export type ManufacturingEstimatePreview =
  | {
      valid: true;
      machineCost: number;
      electricityCost: number;
      postprocessCost: number;
      totalCost: number;
    }
  | {
      valid: false;
      error: "invalid_value" | "incomplete_electricity" | "incomplete_postprocess";
    };

export interface RestoredManufacturingEstimate {
  input: Schemas["ManufacturingEstimateBody"];
  totalCost: number;
  createdAt: string;
}

function finiteNumber(value: unknown, maximum: number): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 && parsed <= maximum ? parsed : null;
}

function optionalNumber(text: string, maximum: number): number | null | undefined {
  const normalized = text.trim().replace(",", ".");
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) && parsed >= 0 && parsed <= maximum
    ? Math.round((parsed + Number.EPSILON) * 10_000) / 10_000
    : undefined;
}

export function manufacturingMetrics(analysis: PrintAnalysis): ManufacturingMetrics | null {
  const metrics = (analysis.report as { metrics?: Record<string, unknown> } | null)?.metrics;
  if (!metrics) return null;
  const printTime = finiteNumber(metrics.print_time_min, 10_000_000);
  const total = finiteNumber(metrics.total_cost, 1_000_000_000_000);
  if (printTime === null || total === null || typeof metrics.currency !== "string") return null;
  const optionalMetric = (key: string, maximum = 1_000_000_000_000) => {
    const value = metrics[key];
    return value == null ? null : finiteNumber(value, maximum);
  };
  const layers = optionalMetric("layers", 10_000_000);
  return {
    mass_g: optionalMetric("mass_g"),
    support_mass_g: optionalMetric("support_mass_g"),
    layers,
    print_time_min: printTime,
    material_cost: optionalMetric("material_cost"),
    support_cost: optionalMetric("support_cost"),
    total_cost: total,
    currency: metrics.currency,
  };
}

/** A persisted analysis is usable only with the controls that produced it. */
export function analysisMatchesManufacturingContext(
  analysis: PrintAnalysis | null,
  versionId: string | null,
  printerProfileId: string,
  materialId: string,
): analysis is PrintAnalysis {
  return Boolean(
    analysis
      && versionId
      && analysis.kind === "analysis"
      && analysis.project_version_id === versionId
      && (analysis.printer_profile_id ?? "") === printerProfileId
      && (analysis.material_id ?? "") === materialId,
  );
}

export function manufacturingEstimateInput(
  draft: ManufacturingRateDraft,
): Schemas["ManufacturingEstimateBody"] | null {
  const machine = optionalNumber(draft.machineRatePerHour, 1_000_000);
  const power = optionalNumber(draft.printerPowerW, 100_000);
  const electricity = optionalNumber(draft.electricityRatePerKwh, 1_000_000);
  const postprocessHours = optionalNumber(draft.postprocessHours, 10_000);
  const postprocessRate = optionalNumber(draft.postprocessRatePerHour, 1_000_000);
  if ([machine, power, electricity, postprocessHours, postprocessRate].includes(undefined)) return null;
  if ((power === null) !== (electricity === null)) return null;
  if ((postprocessHours === null) !== (postprocessRate === null)) return null;
  return {
    machine_rate_per_hour: machine,
    printer_power_w: power,
    electricity_rate_per_kwh: electricity,
    postprocess_hours: postprocessHours,
    postprocess_rate_per_hour: postprocessRate,
  };
}

export function calculateManufacturingEstimate(
  materialTotal: number,
  printTimeMin: number,
  draft: ManufacturingRateDraft,
): ManufacturingEstimatePreview {
  if (!Number.isFinite(materialTotal) || materialTotal < 0 || !Number.isFinite(printTimeMin) || printTimeMin < 0) {
    return { valid: false, error: "invalid_value" };
  }
  const input = manufacturingEstimateInput(draft);
  if (!input) {
    const power = optionalNumber(draft.printerPowerW, 100_000);
    const electricity = optionalNumber(draft.electricityRatePerKwh, 1_000_000);
    if (power !== undefined && electricity !== undefined && (power === null) !== (electricity === null)) {
      return { valid: false, error: "incomplete_electricity" };
    }
    const hours = optionalNumber(draft.postprocessHours, 10_000);
    const rate = optionalNumber(draft.postprocessRatePerHour, 1_000_000);
    if (hours !== undefined && rate !== undefined && (hours === null) !== (rate === null)) {
      return { valid: false, error: "incomplete_postprocess" };
    }
    return { valid: false, error: "invalid_value" };
  }
  const number = (value: number | string | null | undefined) => value == null ? 0 : Number(value);
  const money = (value: number) => Math.round((value + Number.EPSILON) * 100) / 100;
  const printHours = printTimeMin / 60;
  const machineCost = money(printHours * number(input.machine_rate_per_hour));
  const electricityCost = money(
    printHours * (number(input.printer_power_w) / 1000) * number(input.electricity_rate_per_kwh),
  );
  const postprocessCost = money(
    number(input.postprocess_hours) * number(input.postprocess_rate_per_hour),
  );
  const totalCost = money(materialTotal + machineCost + electricityCost + postprocessCost);
  return { valid: true, machineCost, electricityCost, postprocessCost, totalCost };
}

/** Restore only an immutable server snapshot for this exact analysis and source context. */
export function restoredManufacturingEstimate(
  saved: ManufacturingEstimate,
  analysis: PrintAnalysis,
  versionId: string,
  printerProfileId: string,
  materialId: string,
): RestoredManufacturingEstimate | null {
  if (
    saved.analysis_id !== analysis.id
    || saved.project_version_id !== versionId
    || !analysisMatchesManufacturingContext(analysis, versionId, printerProfileId, materialId)
    || (saved.printer_profile_id ?? "") !== printerProfileId
    || saved.material_id !== materialId
    || !/^[A-Za-z]{3}$/.test(saved.currency)
    || !Number.isFinite(Date.parse(saved.created_at))
  ) return null;
  const metrics = manufacturingMetrics(analysis);
  const savedMaterial = finiteNumber(saved.material_cost, 1_000_000_000_000);
  const savedTime = finiteNumber(saved.print_time_min, 10_000_000);
  const savedTotal = finiteNumber(saved.total_cost, 99_999_999_999_999.99);
  if (
    !metrics
    || savedMaterial === null
    || savedTime === null
    || savedTotal === null
    || Math.abs(metrics.total_cost - savedMaterial) > 0.0001
    || Math.abs(metrics.print_time_min - savedTime) > 0.0001
  ) return null;
  const input: Schemas["ManufacturingEstimateBody"] = {
    machine_rate_per_hour: saved.machine_rate_per_hour,
    printer_power_w: saved.printer_power_w,
    electricity_rate_per_kwh: saved.electricity_rate_per_kwh,
    postprocess_hours: saved.postprocess_hours,
    postprocess_rate_per_hour: saved.postprocess_rate_per_hour,
  };
  const draft: ManufacturingRateDraft = {
    machineRatePerHour: saved.machine_rate_per_hour ?? "",
    printerPowerW: saved.printer_power_w ?? "",
    electricityRatePerKwh: saved.electricity_rate_per_kwh ?? "",
    postprocessHours: saved.postprocess_hours ?? "",
    postprocessRatePerHour: saved.postprocess_rate_per_hour ?? "",
  };
  if (!manufacturingEstimateInput(draft)) return null;
  const recomputed = calculateManufacturingEstimate(savedMaterial, savedTime, draft);
  const storedMachine = finiteNumber(saved.machine_cost, 99_999_999_999_999.99);
  const storedElectricity = finiteNumber(saved.electricity_cost, 99_999_999_999_999.99);
  const storedPostprocess = finiteNumber(saved.postprocess_cost, 99_999_999_999_999.99);
  if (
    !recomputed.valid
    || storedMachine === null
    || storedElectricity === null
    || storedPostprocess === null
    || Math.abs(recomputed.machineCost - storedMachine) > 0.011
    || Math.abs(recomputed.electricityCost - storedElectricity) > 0.011
    || Math.abs(recomputed.postprocessCost - storedPostprocess) > 0.011
    || Math.abs(recomputed.totalCost - savedTotal) > 0.011
  ) return null;
  return { input, totalCost: savedTotal, createdAt: saved.created_at };
}
