/** Row-major platform-mm transform for the bounded hinged-lid kinematic preview. */
export function hingedLidTransform(angleDeg: number, pivotZMm: number): number[][] {
  const safeAngle = Number.isFinite(angleDeg) ? Math.max(0, Math.min(180, angleDeg)) : 0;
  const safePivot = Number.isFinite(pivotZMm) ? pivotZMm : 0;
  const angle = safeAngle * Math.PI / 180;
  const rawCosine = Math.cos(angle);
  const rawSine = Math.sin(angle);
  const cosine = Math.abs(rawCosine) < 1e-12 ? 0 : rawCosine;
  const sine = Math.abs(rawSine) < 1e-12 ? 0 : rawSine;
  const negativeSine = sine === 0 ? 0 : -sine;
  return [
    [1, 0, 0, 0],
    [0, cosine, negativeSine, 0],
    [0, sine, cosine, safePivot],
    [0, 0, 0, 1],
  ];
}

/**
 * Row-major platform-mm transform for the bounded sliding-lid preview: the lid's own world
 * matrix times a local +Y travel. The GLB export keys exactly this as glTF translation.
 */
export function slidingLidTransform(
  worldTransform: number[][],
  travelMm: number,
  minTravelMm: number,
  maxTravelMm: number,
): number[][] {
  const low = Number.isFinite(minTravelMm) ? minTravelMm : 0;
  const high = Number.isFinite(maxTravelMm) && maxTravelMm > low ? maxTravelMm : low;
  const travel = Number.isFinite(travelMm) ? Math.max(low, Math.min(high, travelMm)) : low;
  return worldTransform.map((row) => {
    const moved = row.slice();
    moved[3] = (row[3] ?? 0) + (row[1] ?? 0) * travel;
    return moved;
  });
}

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
type MechanismRecord = { kind?: unknown; joint?: JointRecord; validation?: { note?: unknown } };

export type SceneMechanism =
  | { kind: "hinged_lid"; nodeId: string; pivotZMm: number; maxAngleDeg: number }
  | { kind: "sliding_lid"; nodeId: string; minTravelMm: number; maxTravelMm: number };

export type MechanismAssemblyStep = {
  id: string;
  titleRu: string;
  titleEn: string;
  detailRu: string;
  detailEn: string;
  nodeIds: string[];
};

export type MechanismAssemblyGuide = {
  kind: SceneMechanism["kind"];
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

/** A bounded value for the two-second one-joint Studio playback. */
export function mechanismPlaybackValue(min: number, max: number, progress: number): number {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return min;
  const bounded = Number.isFinite(progress) ? Math.max(0, Math.min(1, progress)) : 0;
  return min + (max - min) * bounded;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * The single trusted joint a scene version animates — the same rule the GLB export applies:
 * a malformed record, a hidden lid, or a scene carrying both a hinge and a slide animates nothing.
 */
export function sceneMechanism(
  provenance: Record<string, unknown> | null | undefined,
  visibleNodeIds: ReadonlySet<string>,
): SceneMechanism | null {
  const hinge = provenance?.build_hinged_lid as MechanismRecord | undefined;
  const slide = provenance?.build_sliding_lid as MechanismRecord | undefined;
  if ((hinge === undefined) === (slide === undefined)) return null;
  const record = (hinge ?? slide)!;
  const joint = record?.joint;
  if (!joint || typeof joint !== "object") return null;
  const nodeId = joint.node_id;
  if (typeof nodeId !== "string" || !visibleNodeIds.has(nodeId)) return null;
  if (!["x", "y", "z"].includes(joint.axis as string)) return null;
  if (hinge !== undefined) {
    const low = finite(joint.min_angle_deg ?? 0);
    const high = finite(joint.max_angle_deg ?? 0);
    if (record.kind !== "hinged_lid" || joint.type !== "revolute" || joint.axis !== "x" || low === null || high === null || high <= low) return null;
    const pivot = Array.isArray(joint.pivot_mm) ? finite(joint.pivot_mm[2]) : null;
    return { kind: "hinged_lid", nodeId, pivotZMm: pivot ?? 0, maxAngleDeg: high };
  }
  const low = finite(joint.min_travel_mm ?? 0);
  const high = finite(joint.max_travel_mm ?? 0);
  if (record.kind !== "sliding_lid" || joint.type !== "prismatic" || joint.axis !== "y" || low === null || high === null || high <= low) return null;
  return { kind: "sliding_lid", nodeId, minTravelMm: low, maxTravelMm: high };
}

/**
 * Assembly steps only for the exact generated mechanism whose declared parts are all still
 * present in the visible scene. Arbitrary scenes never receive guessed instructions.
 */
export function mechanismAssemblyGuide(
  provenance: Record<string, unknown> | null | undefined,
  visibleNodeIds: ReadonlySet<string>,
  rawBom: readonly AssemblyBomRecord[],
): MechanismAssemblyGuide | null {
  const mechanism = sceneMechanism(provenance, visibleNodeIds);
  if (!mechanism) return null;
  const raw = provenance?.[
    mechanism.kind === "hinged_lid" ? "build_hinged_lid" : "build_sliding_lid"
  ] as { parts?: Record<string, unknown> } | undefined;
  const part = (name: string): string | null => {
    const value = raw?.parts?.[name];
    return typeof value === "string" && visibleNodeIds.has(value) ? value : null;
  };
  const base = part("base");
  const lid = part("lid");
  if (!base || !lid || base === lid || lid !== mechanism.nodeId) return null;
  const requiredNodeIds = mechanism.kind === "hinged_lid"
    ? [base, lid, part("pin")]
    : [base, lid];
  if (requiredNodeIds.some((nodeId) => nodeId === null)) return null;
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
      || item.node_ids.some((nodeId) => typeof nodeId !== "string")
    ) return null;
    const normalized: MechanismAssemblyBomItem = {
      sourceNodeId: item.source_node_id,
      name: item.name,
      assetId: item.resolved_asset_id,
      quantity: item.quantity as number,
      visibleQuantity: item.visible_quantity as number,
      nodeIds: item.node_ids as string[],
    };
    for (const nodeId of normalized.nodeIds) {
      if (bomByNode.has(nodeId)) return null;
      bomByNode.set(nodeId, normalized);
    }
  }
  const relevantBom: MechanismAssemblyBomItem[] = [];
  for (const nodeId of required) {
    const item = bomByNode.get(nodeId);
    if (!item) return null;
    if (!relevantBom.includes(item)) relevantBom.push(item);
  }
  for (const item of relevantBom) {
    const requiredVisible = item.nodeIds.filter((nodeId) => required.includes(nodeId)).length;
    if (item.visibleQuantity < requiredVisible) return null;
  }
  if (mechanism.kind === "hinged_lid") {
    const pin = part("pin");
    if (!pin || pin === base || pin === lid) return null;
    return {
      kind: mechanism.kind,
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
          detailRu: `Проверьте свободный ход крышки от 0° до ${mechanism.maxAngleDeg}°; прочность и реальный допуск подтверждаются физически.`,
          detailEn: `Check free lid motion from 0° to ${mechanism.maxAngleDeg}°; validate strength and real tolerance physically.`,
          nodeIds: [lid],
        },
      ],
    };
  }
  return {
    kind: mechanism.kind,
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
        detailRu: `Проверьте ход ${mechanism.minTravelMm}–${mechanism.maxTravelMm} мм; трение и реальная посадка подтверждаются физически.`,
        detailEn: `Check the ${mechanism.minTravelMm}–${mechanism.maxTravelMm} mm travel; validate friction and real fit physically.`,
        nodeIds: [lid],
      },
    ],
  };
}
