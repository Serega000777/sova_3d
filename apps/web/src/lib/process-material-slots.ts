export type ProcessMaterialSlot = {
  slot: number;
  material_id: string;
};

type ProcessMaterialAssignment = {
  material_slot: number | null;
};

type ProcessMaterialProfile = {
  material_slots: readonly ProcessMaterialSlot[];
  tool_change_mode: "disabled" | "marlin_tn";
  base_tool: number;
};

export function assignableProcessMaterialSlots(
  profile: ProcessMaterialProfile | null | undefined,
  baseMaterialId: string,
): readonly ProcessMaterialSlot[] {
  if (!profile) return [];
  const baseSlot = profile.material_slots.find((slot) => slot.slot === profile.base_tool);
  if (!baseSlot || baseSlot.material_id !== baseMaterialId) return [];
  if (profile.tool_change_mode === "marlin_tn") return profile.material_slots;
  return [baseSlot];
}

export function sanitizeProcessMaterialAssignments<T extends ProcessMaterialAssignment>(
  modifiers: readonly T[],
  assignableSlots: readonly ProcessMaterialSlot[],
): T[] {
  const allowed = new Set(assignableSlots.map((slot) => slot.slot));
  return modifiers.map((modifier) =>
    modifier.material_slot === null || allowed.has(modifier.material_slot)
      ? modifier
      : { ...modifier, material_slot: null },
  );
}
