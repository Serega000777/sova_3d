import {
  exactHoleSpec,
  MAX_EXACT_DETAIL_MM,
  type Axis,
  type ExactHoleIssue,
  type ExactHoleSpec,
} from "@physical-ai/contracts";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { exactHoleCoordinateCopy } from "./exact-hole-copy";
import { colors, styles } from "./theme";

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <View style={{ width: 138, gap: 4 }}>
      <Text style={styles.muted}>{label}</Text>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChange}
        keyboardType="decimal-pad"
        selectTextOnFocus
      />
    </View>
  );
}

export function ExactHoleSheet({
  visible,
  language,
  busy,
  blockedReason,
  error,
  onClose,
  onApply,
}: {
  visible: boolean;
  language: "ru" | "en";
  busy: boolean;
  blockedReason: string | null;
  error: string | null;
  onClose: () => void;
  onApply: (spec: ExactHoleSpec, label: string) => void;
}) {
  const ru = language === "ru";
  const [axis, setAxis] = useState<Axis>("z");
  const [sign, setSign] = useState<"+" | "-">("+");
  const [positionU, setPositionU] = useState("0");
  const [positionV, setPositionV] = useState("0");
  const [diameter, setDiameter] = useState("5");
  const [through, setThrough] = useState(true);
  const [depth, setDepth] = useState("10");
  const coordinateCopy = exactHoleCoordinateCopy(language, axis);

  const result = useMemo(
    () =>
      exactHoleSpec({
        axis,
        sign,
        positionU,
        positionV,
        diameter,
        through,
        depth,
      }),
    [axis, depth, diameter, positionU, positionV, sign, through],
  );
  const issues: Record<ExactHoleIssue, string> = {
    invalid_position: ru
      ? "Позиции U/V должны быть конечными числами в миллиметрах."
      : "U/V positions must be finite numbers in millimetres.",
    invalid_diameter: ru
      ? `Диаметр должен быть конечным числом от 0 до ${MAX_EXACT_DETAIL_MM} мм.`
      : `Diameter must be a finite number in (0, ${MAX_EXACT_DETAIL_MM}] mm.`,
    invalid_depth: ru
      ? `Глубина глухого отверстия должна быть от 0 до ${MAX_EXACT_DETAIL_MM} мм.`
      : `Blind-hole depth must be in (0, ${MAX_EXACT_DETAIL_MM}] mm.`,
  };

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="78%"
      tabletWidth={520}
      accessibilityLabel={ru ? "Закрыть точное отверстие" : "Close exact hole"}
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.heading}>{ru ? "Точное отверстие" : "Exact hole"}</Text>
        <View style={styles.chip}>
          <Text style={styles.chipText}>B-Rep</Text>
        </View>
        <Pressable
          onPress={onClose}
          hitSlop={12}
          accessibilityLabel={ru ? "Закрыть" : "Close"}
        >
          <Text style={[styles.title, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>
      <Text style={styles.muted}>{coordinateCopy.help}</Text>
      <ScrollView contentContainerStyle={{ gap: 12 }} keyboardShouldPersistTaps="handled">
        <Text style={styles.muted}>{ru ? "Нормаль грани" : "Face normal"}</Text>
        <View style={styles.row}>
          {(["x", "y", "z"] as const).map((item) => (
            <Pressable
              key={item}
              style={[styles.chip, axis === item && { borderColor: colors.selection }]}
              onPress={() => setAxis(item)}
            >
              <Text style={[styles.chipText, axis === item && { color: colors.selection }]}>
                {item.toUpperCase()}
              </Text>
            </Pressable>
          ))}
          {(["+", "-"] as const).map((item) => (
            <Pressable
              key={item}
              style={[styles.chip, sign === item && { borderColor: colors.accent }]}
              onPress={() => setSign(item)}
            >
              <Text style={[styles.chipText, sign === item && { color: colors.accent }]}>
                {item}
              </Text>
            </Pressable>
          ))}
        </View>
        <View style={styles.row}>
          <Field label={coordinateCopy.uLabel} value={positionU} onChange={setPositionU} />
          <Field label={coordinateCopy.vLabel} value={positionV} onChange={setPositionV} />
        </View>
        <View style={styles.row}>
          <Field label={ru ? "Диаметр, мм" : "Diameter, mm"} value={diameter} onChange={setDiameter} />
          {!through ? (
            <Field label={ru ? "Глубина, мм" : "Depth, mm"} value={depth} onChange={setDepth} />
          ) : null}
        </View>
        <View style={[styles.row, { justifyContent: "space-between" }]}>
          <Text style={styles.muted}>{ru ? "Сквозное отверстие" : "Through hole"}</Text>
          <Switch
            value={through}
            disabled={busy}
            onValueChange={setThrough}
            trackColor={{ false: colors.border, true: colors.accent2 }}
          />
        </View>
        {result.issue ? <Text style={styles.error}>{issues[result.issue]}</Text> : null}
        {blockedReason ? <Text style={styles.error}>{blockedReason}</Text> : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <View style={styles.row}>
          <Pressable
            style={[
              styles.button,
              styles.buttonPrimary,
              (!result.spec || blockedReason || busy) && { opacity: 0.45 },
            ]}
            disabled={!result.spec || Boolean(blockedReason) || busy}
            onPress={() => {
              if (!result.spec) return;
              const label = through
                ? `Hole Ø${result.spec.diameter_mm} mm through`
                : `Hole Ø${result.spec.diameter_mm} × ${result.spec.depth_mm} mm`;
              onApply(result.spec, label);
            }}
          >
            <Text style={styles.buttonText}>
              {busy ? (ru ? "Сверлим…" : "Drilling…") : ru ? "Создать отверстие" : "Create hole"}
            </Text>
          </Pressable>
          <Pressable style={styles.button} disabled={busy} onPress={onClose}>
            <Text style={styles.buttonText}>{ru ? "Отмена" : "Cancel"}</Text>
          </Pressable>
        </View>
      </ScrollView>
    </SheetShell>
  );
}
