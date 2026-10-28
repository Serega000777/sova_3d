/** Item 41: client-side view of a text-to-house proposal. Never re-derives the request. */
import type { HouseTextApplyBody, HouseTextProposal } from "./client.js";

export interface HouseTextRow {
  field: HouseTextProposal["diff"][number]["field"];
  label: string;
  value: string;
  source: string | null;
}

const SHAPE = {
  rectangle: { ru: "Прямоугольник", en: "Rectangle" },
  l_shape: { ru: "Г-образный", en: "L-shaped" },
  t_shape: { ru: "Т-образный", en: "T-shaped" },
} as const;

export type HouseFootprintPoint = readonly [number, number];

const PROPOSAL_FIELDS = [
  ["length_mm", "mm"],
  ["width_mm", "mm"],
  ["floor_height_mm", "mm"],
  ["floors", "count"],
  ["shape", "enum"],
] as const;

/** Accept only one internally consistent, target-bound server proposal for confirmation. */
export function houseTextProposalIsExact(
  proposal: HouseTextProposal,
  target: { workspaceId: string; projectId?: string | null },
): boolean {
  const request = proposal.request;
  if (
    proposal.workspace_id !== target.workspaceId
    || (proposal.project_id ?? null) !== (target.projectId ?? null)
    || proposal.job_created !== false
    || proposal.ai_used !== false
    || !Number.isInteger(request.length_mm)
    || !Number.isInteger(request.width_mm)
    || !Number.isInteger(request.floor_height_mm)
    || !Number.isInteger(request.floors)
    || request.floor_height_mm < 2_200
    || request.floor_height_mm > 6_000
    || request.floors < 1
    || request.floors > 3
    || houseTextFootprint(request) === null
    || !Array.isArray(proposal.diff)
    || proposal.diff.length !== PROPOSAL_FIELDS.length
  ) return false;

  const seen = new Set<string>();
  for (const [field, unit] of PROPOSAL_FIELDS) {
    const entries = proposal.diff.filter((entry) => entry.field === field);
    const entry = entries[0];
    if (
      entries.length !== 1
      || !entry
      || seen.has(field)
      || entry.unit !== unit
      || entry.before !== null
      || entry.after !== request[field]
    ) return false;
    seen.add(field);
  }

  const areaRatio = request.shape === "rectangle" ? 1 : request.shape === "l_shape" ? 0.75 : 5 / 9;
  const expectedArea = Math.round(
    request.length_mm * request.width_mm * areaRatio / 1_000,
  ) / 1_000;
  return proposal.total_height_mm === request.floor_height_mm * request.floors
    && proposal.footprint_area_m2 === expectedArea
    && typeof proposal.summary_ru === "string"
    && proposal.summary_ru.trim().length > 0
    && typeof proposal.summary_en === "string"
    && proposal.summary_en.trim().length > 0;
}

/** Exact ground-plane outline used by the bounded house massing shapes, in millimetres. */
export function houseTextFootprint(
  request: HouseTextProposal["request"],
): HouseFootprintPoint[] | null {
  const { length_mm: length, width_mm: width, shape } = request;
  if (
    !Number.isFinite(length)
    || !Number.isFinite(width)
    || length < 2_000
    || length > 50_000
    || width < 2_000
    || width > 50_000
  ) return null;
  if (shape === "rectangle") {
    return [[0, 0], [length, 0], [length, width], [0, width]];
  }
  if (shape === "l_shape") {
    return [
      [0, 0], [length, 0], [length, width / 2],
      [length / 2, width / 2], [length / 2, width], [0, width],
    ];
  }
  if (shape === "t_shape") {
    const third = length / 3;
    return [
      [third, 0], [2 * third, 0], [2 * third, 2 * width / 3],
      [length, 2 * width / 3], [length, width], [0, width],
      [0, 2 * width / 3], [third, 2 * width / 3],
    ];
  }
  return null;
}

/** Human-verifiable rows in the order the server proposed them. */
export function houseTextRows(
  proposal: HouseTextProposal,
  language: "ru" | "en",
): HouseTextRow[] {
  const mm = language === "ru" ? "мм" : "mm";
  return proposal.diff.map((entry) => ({
    field: entry.field,
    label: language === "ru" ? entry.label_ru : entry.label_en,
    value:
      entry.unit === "mm"
        ? `${Number(entry.after).toLocaleString(language)} ${mm}`
        : entry.unit === "enum"
          ? SHAPE[String(entry.after) as keyof typeof SHAPE]?.[language] ?? String(entry.after)
          : String(entry.after),
    source: entry.source ?? null,
  }));
}

/** The apply body is exactly the shown proposal plus the original text, nothing else. */
export function houseTextApplyBody(
  proposal: HouseTextProposal,
  prompt: string,
): HouseTextApplyBody {
  return {
    workspace_id: proposal.workspace_id,
    project_id: proposal.project_id ?? null,
    prompt,
    request: { ...proposal.request },
  };
}

const REFUSALS: Record<string, { ru: string; en: string }> = {
  not_a_house: {
    ru: "Начните с описания дома: «Создай дом …».",
    en: "Start with a house description: “Build a house …”.",
  },
  missing_unit: {
    ru: "У каждого размера нужна единица: мм, см или м.",
    en: "Every dimension needs a unit: mm, cm or m.",
  },
  missing_fields: {
    ru: "Укажите длину, ширину, высоту этажа и число этажей.",
    en: "State length, width, floor height and number of floors.",
  },
  ambiguous_height: {
    ru: "Неясно, какая это высота. Напишите «высота этажа 3 м».",
    en: "Unclear which height this is. Write “floor height 3 m”.",
  },
  conflict: {
    ru: "В описании одно и то же значение задано по-разному.",
    en: "The description gives conflicting values for the same field.",
  },
  unsupported_shape: {
    ru: "По описанию доступны прямоугольная, Г- и Т-образная формы.",
    en: "Text descriptions support rectangular, L-shaped and T-shaped houses.",
  },
  unsupported_feature: {
    ru: "Лестницы, крыши, окна и комнаты по описанию пока не создаются — добавьте их позже в редакторе.",
    en: "Stairs, roofs, windows and rooms are not created from text yet — add them later in the editor.",
  },
  unknown_clause: {
    ru: "Часть описания не распознана. Используйте формат из примера.",
    en: "Part of the description was not recognised. Use the example format.",
  },
  sub_millimetre: {
    ru: "Размеры должны сводиться к целым миллиметрам.",
    en: "Dimensions must resolve to whole millimetres.",
  },
  out_of_range: {
    ru: "Значение вне допустимого диапазона: длина и ширина 2–50 м, высота этажа 2,2–6 м, 1–3 этажа.",
    en: "Value out of range: length and width 2–50 m, floor height 2.2–6 m, 1–3 floors.",
  },
  proposal_mismatch: {
    ru: "Предложение не совпадает с текстом. Получите предложение заново.",
    en: "The proposal no longer matches the text. Request it again.",
  },
  project_has_head: {
    ru: "Проект уже содержит версии; дом по описанию создаётся только в пустом проекте.",
    en: "The project already has versions; a described house only starts an empty project.",
  },
};

/** A clear message for a fail-closed refusal; unknown reasons fall back to the server text. */
export function houseTextRefusal(
  details: unknown,
  fallback: string,
  language: "ru" | "en",
): string {
  const reason =
    details && typeof details === "object" && "reason" in details
      ? String((details as { reason: unknown }).reason)
      : null;
  const known = reason ? REFUSALS[reason] : undefined;
  if (!known) return fallback;
  const fragment =
    details && typeof details === "object" && "fragment" in details
      ? String((details as { fragment: unknown }).fragment)
      : null;
  return fragment ? `${known[language]} («${fragment}»)` : known[language];
}
