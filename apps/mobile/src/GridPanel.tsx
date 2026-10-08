import { GRID_STEPS_MM, type ModellingGrid } from "@physical-ai/contracts";
import { Modal, Pressable, ScrollView, Switch, Text, View } from "react-native";

import { colors, styles } from "./theme";

const AXES = [
  ["x", colors.symmetryX],
  ["y", colors.symmetryY],
  ["z", colors.symmetryZ],
] as const;

export function GridPanel({
  visible,
  grid,
  onChange,
  onClose,
}: {
  visible: boolean;
  grid: ModellingGrid;
  onChange: (grid: ModellingGrid) => void;
  onClose: () => void;
}) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.35)", justifyContent: "flex-end" }}>
        <Pressable style={{ flex: 1 }} onPress={onClose} accessibilityLabel="Close grid controls" />
        <View
          style={{
            maxHeight: "42%",
            backgroundColor: colors.panel,
            borderTopLeftRadius: 22,
            borderTopRightRadius: 22,
            padding: 16,
            gap: 12,
          }}
        >
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <Text style={styles.heading}>Grid & symmetry</Text>
            <Pressable onPress={onClose} hitSlop={12} accessibilityLabel="Close">
              <Text style={[styles.title, { color: colors.muted }]}>×</Text>
            </Pressable>
          </View>
          <Text style={styles.muted}>Grid step, mm</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
            {GRID_STEPS_MM.map((step) => (
              <Pressable
                key={step}
                style={[styles.chip, grid.step_mm === step && { borderColor: colors.accent }]}
                onPress={() => onChange({ ...grid, step_mm: step })}
              >
                <Text style={[styles.chipText, grid.step_mm === step && { color: colors.accent }]}>
                  {step}
                </Text>
              </Pressable>
            ))}
          </ScrollView>
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <View style={{ flex: 1 }}>
              <Text style={styles.text}>Snap</Text>
              <Text style={styles.muted}>Rounds touch input to the shown grid step.</Text>
            </View>
            <Switch
              value={grid.snap}
              onValueChange={(snap) => onChange({ ...grid, snap })}
              trackColor={{ false: colors.border, true: colors.accent2 }}
              thumbColor={grid.snap ? colors.accent : colors.muted}
            />
          </View>
          <Text style={styles.muted}>Symmetry planes</Text>
          <View style={styles.row}>
            {AXES.map(([axis, colour]) => {
              const enabled = grid.symmetry[axis];
              return (
                <Pressable
                  key={axis}
                  style={[styles.chip, enabled && { borderColor: colour }]}
                  onPress={() =>
                    onChange({
                      ...grid,
                      symmetry: { ...grid.symmetry, [axis]: !enabled },
                    })
                  }
                >
                  <Text style={[styles.chipText, { color: enabled ? colour : colors.text }]}>
                    {axis.toUpperCase()} {enabled ? "on" : "off"}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      </View>
    </Modal>
  );
}
