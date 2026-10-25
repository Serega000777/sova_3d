export type EngineeringIntent = "walls" | "strength" | "material" | "fastener" | "fit" | "overview";
export type EngineeringVerdict = "yes" | "no" | "unsure" | "info";
export type EngineeringVerdictTone = "positive" | "negative" | "caution";

/**
 * Strength asks whether a part holds the requested load; the other checks ask whether a
 * problem exists. Their yes/no colours therefore have opposite meanings.
 */
export function engineeringVerdictTone(
  intent: EngineeringIntent,
  verdict: EngineeringVerdict,
): EngineeringVerdictTone {
  if (verdict !== "yes" && verdict !== "no") return "caution";
  if (intent === "strength") return verdict === "yes" ? "positive" : "negative";
  return verdict === "yes" ? "negative" : "positive";
}
