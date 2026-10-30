export type MaterialSlotPayload = {
  slot: number;
  material_id: string;
};

export function buildPrinterProfileCreatePayload({
  workspaceId,
  printerModelId,
  name,
  defaultMaterialId,
  isDefault,
}: {
  workspaceId: string;
  printerModelId: string;
  name: string;
  defaultMaterialId: string;
  isDefault: boolean;
}) {
  return {
    workspace_id: workspaceId,
    printer_model_id: printerModelId,
    name,
    default_material_id: defaultMaterialId,
    is_default: isDefault,
  };
}

export function buildMaterialSlotsUpdate(slots: readonly MaterialSlotPayload[]) {
  return {
    material_slots: slots.map((slot) => ({ ...slot })),
  };
}
