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
