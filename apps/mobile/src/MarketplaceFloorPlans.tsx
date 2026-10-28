import type { FloorPlan, Listing, PlanOpening } from "@physical-ai/contracts";
import { useMemo, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { PlanViewer } from "./PlanViewer";
import type { PlanEntitySelection } from "./plan-link";
import { colors, styles } from "./theme";

type FloorPlanRow = Listing["floor_plans"][number];

function previewPlan(level: FloorPlanRow): FloorPlan {
  return {
    ...level.plan,
    openings: level.plan.openings.map((opening) => ({
      ...opening,
      kind: opening.kind as PlanOpening["kind"],
      height_mm: opening.height_mm ?? undefined,
    })),
  };
}

export function MarketplaceFloorPlans({ levels }: { levels: readonly FloorPlanRow[] }) {
  const [selectedFloor, setSelectedFloor] = useState(levels[0]?.floor_index ?? 0);
  const [selection, setSelection] = useState<PlanEntitySelection | null>(null);
  const selected = useMemo(
    () => levels.find((level) => level.floor_index === selectedFloor) ?? levels[0] ?? null,
    [levels, selectedFloor],
  );
  const plan = useMemo(() => selected ? previewPlan(selected) : null, [selected]);
  if (!selected || !plan) return null;

  return (
    <View style={[styles.card, { gap: 10 }]} accessibilityLabel="Поэтажные планы">
      <View style={{ gap: 3 }}>
        <Text style={styles.heading}>Поэтажные планы</Text>
        <Text style={styles.sectionSubtitle}>Структурированный план из опубликованной неизменяемой версии.</Text>
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }} accessibilityRole="tablist">
        {levels.map((level) => (
          <Pressable
            key={level.floor_index}
            accessibilityRole="tab"
            accessibilityState={{ selected: level.floor_index === selected.floor_index }}
            onPress={() => {
              setSelectedFloor(level.floor_index);
              setSelection(null);
            }}
            style={[styles.chip, level.floor_index === selected.floor_index && { backgroundColor: colors.accentWashStrong, borderColor: colors.accent }]}
          >
            <Text style={[styles.chipText, level.floor_index === selected.floor_index && { color: colors.accent }]}>{level.floor_index + 1} этаж</Text>
          </Pressable>
        ))}
      </View>
      <PlanViewer plan={plan} selection={selection} onSelect={setSelection} height={300} />
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        <View style={styles.chip}><Text style={styles.chipText}>{plan.walls.length} стен</Text></View>
        {plan.rooms.length > 0 ? <View style={styles.chip}><Text style={styles.chipText}>{plan.rooms.length} комн.</Text></View> : null}
        <View style={styles.chip}><Text style={styles.chipText}>Отметка: {(selected.elevation_mm / 1000).toFixed(1)} м</Text></View>
      </View>
    </View>
  );
}
