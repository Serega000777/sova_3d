import { GRID_STEPS_MM, type ModellingGrid } from "@physical-ai/contracts";
import { Pressable, ScrollView, Switch, Text, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

const AXES = [
  ["x", colors.symmetryX],
  ["y", colors.symmetryY],
  ["z", colors.symmetryZ],
] as const;

export function GridPanel({
  visible,
  language,
  grid,
  onChange,
  onClose,
}: {
  visible: boolean;
  language: "ru" | "en";
  grid: ModellingGrid;
  onChange: (grid: ModellingGrid) => void;
  onClose: () => void;
}) {
  const ru = language === "ru";
  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="42%"
      phoneBackdropColor="rgba(0,0,0,0.35)"
      accessibilityLabel={ru ? "Закрыть настройки сетки" : "Close grid controls"}
      contentGap={12}
    >
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <Text style={styles.heading}>{ru ? "Сетка и симметрия" : "Grid & symmetry"}</Text>
            <Pressable
              onPress={onClose}
              hitSlop={12}
              accessibilityLabel={ru ? "Закрыть" : "Close"}
            >
              <Text style={[styles.title, { color: colors.muted }]}>×</Text>
            </Pressable>
          </View>
          <Text style={styles.muted}>{ru ? "Шаг сетки, мм" : "Grid step, mm"}</Text>
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
              <Text style={styles.text}>{ru ? "Привязка" : "Snap"}</Text>
              <Text style={styles.muted}>
                {ru
                  ? "Округляет координаты касания до указанного шага сетки."
                  : "Rounds touch input to the shown grid step."}
              </Text>
            </View>
            <Switch
              value={grid.snap}
              onValueChange={(snap) => onChange({ ...grid, snap })}
              trackColor={{ false: colors.border, true: colors.accent2 }}
              thumbColor={grid.snap ? colors.accent : colors.muted}
            />
          </View>
          <Text style={styles.muted}>{ru ? "Плоскости симметрии" : "Symmetry planes"}</Text>
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
                    {axis.toUpperCase()}{" "}
                    {enabled ? (ru ? "вкл." : "on") : ru ? "выкл." : "off"}
                  </Text>
                </Pressable>
              );
            })}
          </View>
    </SheetShell>
  );
}
