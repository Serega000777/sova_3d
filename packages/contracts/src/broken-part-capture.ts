/** User-labelled evidence plan for reference 72 (broken-part photogrammetry). */

export const BROKEN_PART_SECTIONS = [
  {
    id: "whole",
    titleRu: "Весь объект",
    guidanceRu: "Обойдите деталь и снимите все сохранившиеся внешние стороны с перекрытием.",
    targetFrames: 8,
  },
  {
    id: "fracture",
    titleRu: "Граница слома",
    guidanceRu: "Снимите край повреждения крупно под разными углами; не выдавайте его за восстановленный контур.",
    targetFrames: 4,
  },
  {
    id: "interior",
    titleRu: "Внутри и снизу",
    guidanceRu: "Покажите полости, нижнюю сторону и места крепления, которые видимы камерой.",
    targetFrames: 4,
  },
] as const;

export type BrokenPartSectionId = (typeof BROKEN_PART_SECTIONS)[number]["id"];
export type BrokenPartSectionCounts = Record<BrokenPartSectionId, number>;

export const emptyBrokenPartSectionCounts: BrokenPartSectionCounts = {
  whole: 0,
  fracture: 0,
  interior: 0,
};

export function uncoveredBrokenPartSections(
  counts: BrokenPartSectionCounts,
): (typeof BROKEN_PART_SECTIONS)[number][] {
  return BROKEN_PART_SECTIONS.filter((section) => counts[section.id] < section.targetFrames);
}

export function brokenPartCoveragePercent(counts: BrokenPartSectionCounts): number {
  const captured = BROKEN_PART_SECTIONS.reduce(
    (sum, section) => sum + Math.min(Math.max(counts[section.id], 0), section.targetFrames),
    0,
  );
  const target = BROKEN_PART_SECTIONS.reduce((sum, section) => sum + section.targetFrames, 0);
  return Math.round((captured / target) * 100);
}

export function parseBrokenPartScaleMm(value: string): number | null {
  const parsed = Number(value.trim().replace(",", "."));
  return Number.isFinite(parsed) && parsed >= 1 && parsed <= 10_000 ? parsed : null;
}
