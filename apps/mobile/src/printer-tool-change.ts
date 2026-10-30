export type ToolChangeMode = "disabled" | "marlin_tn";

export type MaterialSlotDraft = {
  slot: number;
  material_id: string;
};

export type ToolChangeDraft = {
  tool_change_mode: ToolChangeMode;
  tool_count: number;
  base_tool: number;
  purge_tower_enabled: boolean;
  purge_tower_width_mm: number;
  purge_volume_mm3: number;
  material_slots: MaterialSlotDraft[];
};

export type ValidToolChangeConfig = ToolChangeDraft;

export type ToolChangeValidation =
  | { ok: true; value: ValidToolChangeConfig }
  | { ok: false; error: string };

export function nextAvailableMaterialSlot(
  mode: ToolChangeMode,
  toolCount: number,
  slots: readonly MaterialSlotDraft[],
): number | undefined {
  const limit = mode === "disabled"
    ? 16
    : Number.isFinite(toolCount) && Number.isInteger(toolCount) && toolCount >= 1
      ? Math.min(toolCount, 16)
      : 0;
  for (let slot = 0; slot < limit; slot += 1) {
    if (!slots.some((item) => item.slot === slot)) return slot;
  }
  return undefined;
}

/** Validate one complete capability + loaded-inventory update before the API call. */
export function validateToolChangeConfig(
  draft: ToolChangeDraft,
  knownMaterialIds: readonly string[],
  defaultMaterialId: string | null,
): ToolChangeValidation {
  if (draft.tool_change_mode !== "disabled" && draft.tool_change_mode !== "marlin_tn") {
    return { ok: false, error: "Неизвестный режим смены инструмента." };
  }
  if (!Number.isInteger(draft.tool_count) || draft.tool_count < 1 || draft.tool_count > 16) {
    return { ok: false, error: "Количество инструментов должно быть от 1 до 16." };
  }
  if (!Number.isInteger(draft.base_tool) || draft.base_tool < 0 || draft.base_tool > 15) {
    return { ok: false, error: "Базовый инструмент должен быть от T0 до T15." };
  }
  if (draft.tool_change_mode === "marlin_tn" && draft.tool_count < 2) {
    return { ok: false, error: "Generic Marlin Tn требует минимум два инструмента." };
  }
  if (draft.tool_change_mode === "marlin_tn" && draft.base_tool >= draft.tool_count) {
    return { ok: false, error: "Базовый инструмент выходит за настроенный диапазон." };
  }
  if (draft.tool_change_mode === "disabled" && draft.purge_tower_enabled) {
    return { ok: false, error: "Purge-башня требует режима Generic Marlin Tn." };
  }
  if (
    !Number.isFinite(draft.purge_tower_width_mm)
    || draft.purge_tower_width_mm < 10
    || draft.purge_tower_width_mm > 40
  ) {
    return { ok: false, error: "Ширина purge-башни должна быть от 10 до 40 мм." };
  }
  if (
    !Number.isFinite(draft.purge_volume_mm3)
    || draft.purge_volume_mm3 < 10
    || draft.purge_volume_mm3 > 500
  ) {
    return { ok: false, error: "Purge на переход должен быть от 10 до 500 мм³." };
  }

  const known = new Set(knownMaterialIds);
  const occupied = new Set<number>();
  for (const item of draft.material_slots) {
    if (!Number.isInteger(item.slot) || item.slot < 0 || item.slot > 15) {
      return { ok: false, error: "Загруженный слот должен быть от T0 до T15." };
    }
    if (draft.tool_change_mode === "marlin_tn" && item.slot >= draft.tool_count) {
      return { ok: false, error: "Загруженный слот выходит за диапазон инструментов." };
    }
    if (occupied.has(item.slot)) {
      return { ok: false, error: `Слот T${item.slot} указан больше одного раза.` };
    }
    if (!known.has(item.material_id)) {
      return { ok: false, error: `Материал слота T${item.slot} отсутствует в каталоге.` };
    }
    occupied.add(item.slot);
  }

  if (
    draft.material_slots.length > 0
    && defaultMaterialId
    && !draft.material_slots.some((item) => item.material_id === defaultMaterialId)
  ) {
    return { ok: false, error: "Материал по умолчанию должен быть загружен в один из слотов." };
  }

  if (draft.tool_change_mode === "marlin_tn") {
    const baseSlot = draft.material_slots.find((item) => item.slot === draft.base_tool);
    if (!baseSlot) {
      return { ok: false, error: `Базовый слот T${draft.base_tool} должен быть загружен.` };
    }
    if (defaultMaterialId && baseSlot.material_id !== defaultMaterialId) {
      return { ok: false, error: "Материал базового слота должен совпадать с материалом по умолчанию." };
    }
  }

  return {
    ok: true,
    value: {
      ...draft,
      material_slots: [...draft.material_slots].sort((left, right) => left.slot - right.slot),
    },
  };
}
