/** T-232: deterministic exterior-capture coverage shared by mobile and API-facing tests. */
export type ExteriorSectionId = "front" | "right" | "back" | "left" | "roof";

export interface ExteriorSection {
  id: ExteriorSectionId;
  titleRu: string;
  guidanceRu: string;
  targetFrames: number;
  required: boolean;
}

export const EXTERIOR_SECTIONS: readonly ExteriorSection[] = [
  { id: "front", titleRu: "Главный фасад", guidanceRu: "Сделайте проход слева направо с перекрытием кадров.", targetFrames: 8, required: true },
  { id: "right", titleRu: "Правая сторона", guidanceRu: "Захватите угол предыдущего фасада и пройдите всю стену.", targetFrames: 8, required: true },
  { id: "back", titleRu: "Задний фасад", guidanceRu: "Снимите стену и оба угла; не пропускайте проёмы.", targetFrames: 8, required: true },
  { id: "left", titleRu: "Левая сторона", guidanceRu: "Замкните обход, повторив угол главного фасада.", targetFrames: 8, required: true },
  { id: "roof", titleRu: "Крыша (если безопасно)", guidanceRu: "Снимайте только с земли, окна или разрешённой площадки — не поднимайтесь ради кадра.", targetFrames: 6, required: false },
];

export type ExteriorSectionCounts = Record<ExteriorSectionId, number>;

export function emptyExteriorSectionCounts(): ExteriorSectionCounts {
  return { front: 0, right: 0, back: 0, left: 0, roof: 0 };
}

export function normalizeExteriorSectionCounts(value: unknown): ExteriorSectionCounts {
  const source = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const counts = emptyExteriorSectionCounts();
  for (const section of EXTERIOR_SECTIONS) {
    const count = Number(source[section.id]);
    counts[section.id] = Number.isFinite(count) && count > 0 ? Math.floor(count) : 0;
  }
  return counts;
}

export function uncoveredExteriorSections(counts: ExteriorSectionCounts): ExteriorSection[] {
  return EXTERIOR_SECTIONS.filter(
    (section) => section.required && counts[section.id] < section.targetFrames,
  );
}

export function exteriorCoveragePercent(counts: ExteriorSectionCounts): number {
  const required = EXTERIOR_SECTIONS.filter((section) => section.required);
  const covered = required.reduce(
    (sum, section) => sum + Math.min(counts[section.id], section.targetFrames),
    0,
  );
  const target = required.reduce((sum, section) => sum + section.targetFrames, 0);
  return target ? Math.round((covered / target) * 100) : 0;
}
