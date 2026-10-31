import type { GenerationEstimate } from "@physical-ai/contracts";

/** Present a bounded range in whole minutes without inventing false precision. */
export function formatGenerationEstimate(
  estimate: GenerationEstimate,
  ru: boolean,
): string | null {
  if (
    !estimate.provider.trim()
    || !estimate.model.trim()
    || estimate.target_format !== "glb"
    || !Number.isFinite(estimate.latency_seconds_min)
    || !Number.isFinite(estimate.latency_seconds_max)
    || estimate.latency_seconds_min < 0
    || estimate.latency_seconds_max < estimate.latency_seconds_min
    || (estimate.credits != null && (!estimate.credits.trim() || estimate.credits.length > 64))
    || (estimate.cost_usd != null && !/^(0|[1-9]\d*)(\.\d{1,6})?$/.test(estimate.cost_usd))
  ) return null;
  const min = Math.max(1, Math.round(estimate.latency_seconds_min / 60));
  const max = Math.max(min, Math.round(estimate.latency_seconds_max / 60));
  const latency = min === max
    ? `~${min} ${ru ? "мин" : "min"}`
    : `${min}–${max} ${ru ? "мин" : "min"}`;
  const credits = estimate.credits ?? "?";
  const cost = estimate.cost_usd == null
    ? ru
      ? "self-hosted — точная цена в USD недоступна"
      : "self-hosted — exact USD price unavailable"
    : `$${estimate.cost_usd}`;
  return ru
    ? `Оценка до запуска: ${latency}, ${credits} кредитов (${cost}).`
    : `Pre-launch estimate: ${latency}, ${credits} credits (${cost}).`;
}
