type JointRecord = {
  type?: unknown;
  node_id?: unknown;
  axis?: unknown;
  pivot_mm?: unknown;
  min_angle_deg?: unknown;
  max_angle_deg?: unknown;
  min_travel_mm?: unknown;
  max_travel_mm?: unknown;
};

type MechanismRecord = {
  kind?: unknown;
  joint?: JointRecord;
  parts?: Record<string, unknown>;
};

export type MechanismAssemblyStep = {
  id: string;
  titleRu: string;
  titleEn: string;
  detailRu: string;
  detailEn: string;
  nodeIds: string[];
};

export type MechanismAssemblyGuide = {
  kind: "hinged_lid" | "sliding_lid";
  steps: MechanismAssemblyStep[];
  bom: MechanismAssemblyBomItem[];
};

export type MechanismAssemblyBomItem = {
  sourceNodeId: string;
  name: string;
  assetId: string;
  quantity: number;
  visibleQuantity: number;
  nodeIds: string[];
};

type AssemblyBomRecord = {
  source_node_id?: unknown;
  name?: unknown;
  resolved_asset_id?: unknown;
  quantity?: unknown;
  visible_quantity?: unknown;
  node_ids?: unknown;
};

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Returns steps only for one exact server-generated mechanism whose declared parts are all
 * still visible in this immutable scene version. Arbitrary or conflicting provenance fails closed.
 */
export function mechanismAssemblyGuide(
  provenance: Record<string, unknown> | null | undefined,
  visibleNodeIds: ReadonlySet<string>,
  rawBom: readonly AssemblyBomRecord[],
): MechanismAssemblyGuide | null {
  const hinge = provenance?.build_hinged_lid as MechanismRecord | undefined;
  const slide = provenance?.build_sliding_lid as MechanismRecord | undefined;
  if ((hinge === undefined) === (slide === undefined)) return null;

  const record = (hinge ?? slide)!;
  const joint = record.joint;
  const nodeId = joint?.node_id;
  if (!joint || typeof nodeId !== "string" || !visibleNodeIds.has(nodeId)) return null;

  const part = (name: string): string | null => {
    const value = record.parts?.[name];
    return typeof value === "string" && visibleNodeIds.has(value) ? value : null;
  };
  const base = part("base");
  const lid = part("lid");
  if (!base || !lid || base === lid || lid !== nodeId) return null;

  const requiredNodeIds = hinge ? [base, lid, part("pin")] : [base, lid];
  if (requiredNodeIds.some((partNodeId) => partNodeId === null)) return null;
  const required = requiredNodeIds as string[];
  const bomByNode = new Map<string, MechanismAssemblyBomItem>();
  for (const item of rawBom) {
    if (
      typeof item.source_node_id !== "string"
      || typeof item.name !== "string"
      || typeof item.resolved_asset_id !== "string"
      || !Number.isInteger(item.quantity)
      || (item.quantity as number) < 1
      || !Number.isInteger(item.visible_quantity)
      || (item.visible_quantity as number) < 0
      || (item.visible_quantity as number) > (item.quantity as number)
      || !Array.isArray(item.node_ids)
      || item.node_ids.length !== item.quantity
      || item.node_ids.some((itemNodeId) => typeof itemNodeId !== "string")
    ) return null;
    const normalized: MechanismAssemblyBomItem = {
      sourceNodeId: item.source_node_id,
      name: item.name,
      assetId: item.resolved_asset_id,
      quantity: item.quantity as number,
      visibleQuantity: item.visible_quantity as number,
      nodeIds: item.node_ids as string[],
    };
    for (const itemNodeId of normalized.nodeIds) {
      if (bomByNode.has(itemNodeId)) return null;
      bomByNode.set(itemNodeId, normalized);
    }
  }
  const relevantBom: MechanismAssemblyBomItem[] = [];
  for (const requiredNodeId of required) {
    const item = bomByNode.get(requiredNodeId);
    if (!item) return null;
    if (!relevantBom.includes(item)) relevantBom.push(item);
  }
  for (const item of relevantBom) {
    const requiredVisible = item.nodeIds.filter((itemNodeId) => required.includes(itemNodeId)).length;
    if (item.visibleQuantity < requiredVisible) return null;
  }

  if (hinge) {
    const low = finite(joint.min_angle_deg ?? 0);
    const high = finite(joint.max_angle_deg ?? 0);
    const pin = part("pin");
    if (
      record.kind !== "hinged_lid"
      || joint.type !== "revolute"
      || joint.axis !== "x"
      || low === null
      || high === null
      || high <= low
      || !pin
      || pin === base
      || pin === lid
    ) return null;
    return {
      kind: "hinged_lid",
      bom: relevantBom,
      steps: [
        {
          id: "inspect-parts",
          titleRu: "Проверьте три детали",
          titleEn: "Check the three parts",
          detailRu: "Основание, крышка и съёмный штифт должны присутствовать в этой версии сцены.",
          detailEn: "The base, lid and removable pin must all be present in this scene version.",
          nodeIds: [base, lid, pin],
        },
        {
          id: "align-hinge",
          titleRu: "Совместите шарнир",
          titleEn: "Align the hinge",
          detailRu: "Посадите крышку на основание и совместите отверстия шарнирных проушин.",
          detailEn: "Seat the lid on the base and align the hinge-knuckle holes.",
          nodeIds: [base, lid],
        },
        {
          id: "insert-pin",
          titleRu: "Вставьте съёмный штифт",
          titleEn: "Insert the removable pin",
          detailRu: "Проведите сохранённый штифт через совмещённые проушины без силовой посадки.",
          detailEn: "Pass the saved pin through the aligned knuckles without forcing the fit.",
          nodeIds: [pin],
        },
        {
          id: "verify-motion",
          titleRu: "Проверьте движение",
          titleEn: "Verify motion",
          detailRu: `Проверьте свободный ход крышки от ${low}° до ${high}°; прочность и реальный допуск подтверждаются физически.`,
          detailEn: `Check free lid motion from ${low}° to ${high}°; validate strength and real tolerance physically.`,
          nodeIds: [lid],
        },
      ],
    };
  }

  const low = finite(joint.min_travel_mm ?? 0);
  const high = finite(joint.max_travel_mm ?? 0);
  if (
    record.kind !== "sliding_lid"
    || joint.type !== "prismatic"
    || joint.axis !== "y"
    || low === null
    || high === null
    || high <= low
  ) return null;
  return {
    kind: "sliding_lid",
    bom: relevantBom,
    steps: [
      {
        id: "inspect-parts",
        titleRu: "Проверьте две детали",
        titleEn: "Check the two parts",
        detailRu: "Корпус с направляющими и отдельная крышка должны присутствовать в этой версии сцены.",
        detailEn: "The guided base and separate lid must both be present in this scene version.",
        nodeIds: [base, lid],
      },
      {
        id: "align-guides",
        titleRu: "Совместите направляющие",
        titleEn: "Align the guides",
        detailRu: "Расположите крышку у входа в направляющие корпуса по её сохранённой оси +Y.",
        detailEn: "Place the lid at the guide entrance along its persisted local +Y axis.",
        nodeIds: [base, lid],
      },
      {
        id: "seat-lid",
        titleRu: "Заведите крышку",
        titleEn: "Seat the lid",
        detailRu: "Плавно сдвиньте крышку в направляющие, не изменяя ориентацию детали.",
        detailEn: "Slide the lid smoothly into the guides without changing its orientation.",
        nodeIds: [lid],
      },
      {
        id: "verify-motion",
        titleRu: "Проверьте полный ход",
        titleEn: "Verify full travel",
        detailRu: `Проверьте ход ${low}–${high} мм; трение и реальная посадка подтверждаются физически.`,
        detailEn: `Check the ${low}–${high} mm travel; validate friction and real fit physically.`,
        nodeIds: [lid],
      },
    ],
  };
}
