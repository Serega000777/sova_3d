export type StudioToolId = "select" | "paint" | "mesh" | "grid" | "layers" | "dimensions";
export type StudioTabId = "properties" | "check" | "versions";

export type StudioCatalogAction = {
  id: string;
  group: "edit" | "organize" | "review";
  label: Record<"ru" | "en", string>;
  target:
    | { kind: "tool"; id: StudioToolId }
    | { kind: "tab"; id: StudioTabId }
    | { kind: "export" };
  disabled: boolean;
};

const DEFINITIONS: Array<Omit<StudioCatalogAction, "disabled"> & {
  needs: "model" | "version";
}> = [
  { id: "select", group: "edit", label: { ru: "Выделение", en: "Selection" }, target: { kind: "tool", id: "select" }, needs: "model" },
  { id: "paint", group: "edit", label: { ru: "Покраска", en: "Paint" }, target: { kind: "tool", id: "paint" }, needs: "model" },
  { id: "mesh", group: "edit", label: { ru: "Правка сетки", en: "Mesh edit" }, target: { kind: "tool", id: "mesh" }, needs: "model" },
  { id: "dimensions", group: "edit", label: { ru: "Размеры", en: "Dimensions" }, target: { kind: "tool", id: "dimensions" }, needs: "model" },
  { id: "grid", group: "organize", label: { ru: "Сетка и привязка", en: "Grid and snap" }, target: { kind: "tool", id: "grid" }, needs: "model" },
  { id: "layers", group: "organize", label: { ru: "Слои и модификаторы", en: "Layers and modifiers" }, target: { kind: "tool", id: "layers" }, needs: "version" },
  { id: "properties", group: "organize", label: { ru: "Свойства объекта", en: "Object properties" }, target: { kind: "tab", id: "properties" }, needs: "version" },
  { id: "check", group: "review", label: { ru: "Проверка модели", en: "Model check" }, target: { kind: "tab", id: "check" }, needs: "version" },
  { id: "versions", group: "review", label: { ru: "Версии", en: "Versions" }, target: { kind: "tab", id: "versions" }, needs: "version" },
  { id: "export", group: "review", label: { ru: "Экспорт", en: "Export" }, target: { kind: "export" }, needs: "version" },
];

export function studioCatalogActions({
  modelAvailable,
  activeAvailable,
}: {
  modelAvailable: boolean;
  activeAvailable: boolean;
}): StudioCatalogAction[] {
  return DEFINITIONS.map(({ needs, ...action }) => ({
    ...action,
    disabled: needs === "model" ? !modelAvailable : !activeAvailable,
  }));
}
