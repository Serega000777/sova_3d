import type { Component } from "@physical-ai/contracts";

export type ComponentCategory = "all" | "favorites" | "electronics" | "mechanics";

const ELECTRONIC_KINDS = new Set(["board", "module", "sensor", "display", "battery"]);

export function componentKindLabel(kind: string): string {
  return {
    board: "Плата",
    module: "Модуль",
    sensor: "Датчик",
    display: "Дисплей",
    battery: "Батарея",
    fan: "Вентилятор",
    motor: "Мотор",
  }[kind] ?? kind;
}

export function componentLibraryView(
  components: readonly Component[],
  query: string,
  category: ComponentCategory,
  favoriteIds: ReadonlySet<string> = new Set(),
): Component[] {
  const words = query.toLocaleLowerCase("ru-RU").split(/\s+/).filter(Boolean);
  return components.filter((component) => {
    const group = ELECTRONIC_KINDS.has(component.kind) ? "electronics" : "mechanics";
    if (category === "favorites" && !favoriteIds.has(component.id)) return false;
    if (category !== "all" && category !== "favorites" && category !== group) return false;
    const haystack = [component.name, component.kind, component.screw, ...component.aliases]
      .join(" ")
      .toLocaleLowerCase("ru-RU");
    return words.every((word) => haystack.includes(word));
  });
}
