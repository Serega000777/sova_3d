import {
  MAX_EXACT_DETAIL_MM,
  shellSpec,
  type Axis,
  type ExactShellSpec,
} from "@physical-ai/contracts";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

export function ExactShellSheet({
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
  onApply: (spec: ExactShellSpec, label: string) => void;
}) {
  const ru = language === "ru";
  const [thickness, setThickness] = useState("2");
  const [openFace, setOpenFace] = useState(false);
  const [axis, setAxis] = useState<Axis>("z");
  const [sign, setSign] = useState<"+" | "-">("+");
  const result = useMemo(
    () => shellSpec({ thickness, openFace, axis, sign }),
    [axis, openFace, sign, thickness],
  );

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="62%"
      tabletWidth={520}
      accessibilityLabel={ru ? "Закрыть точную оболочку" : "Close exact shell"}
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.heading}>{ru ? "Точная оболочка" : "Exact shell"}</Text>
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
      <Text style={styles.muted}>
        {ru
          ? "Создаёт полую оболочку заданной толщины. Можно оставить её замкнутой или открыть одну плоскую грань по мировой нормали."
          : "Creates a hollow shell with the chosen wall thickness. Keep it closed or open one planar face by its world normal."}
      </Text>
      <ScrollView contentContainerStyle={{ gap: 12 }} keyboardShouldPersistTaps="handled">
        <View style={{ width: 180, gap: 4 }}>
          <Text style={styles.muted}>{ru ? "Толщина стенки, мм" : "Wall thickness, mm"}</Text>
          <TextInput
            style={styles.input}
            value={thickness}
            onChangeText={setThickness}
            keyboardType="decimal-pad"
            selectTextOnFocus
          />
        </View>
        <View style={{ gap: 6 }}>
          <Text style={styles.muted}>{ru ? "Результат" : "Result"}</Text>
          <View style={styles.row}>
            <Pressable
              style={[styles.chip, !openFace && { borderColor: colors.accent }]}
              disabled={busy}
              onPress={() => setOpenFace(false)}
            >
              <Text style={styles.chipText}>{ru ? "Замкнутая" : "Closed"}</Text>
            </Pressable>
            <Pressable
              style={[styles.chip, openFace && { borderColor: colors.accent }]}
              disabled={busy}
              onPress={() => setOpenFace(true)}
            >
              <Text style={styles.chipText}>{ru ? "Открытая грань" : "Open face"}</Text>
            </Pressable>
          </View>
        </View>
        {openFace ? (
          <View style={{ gap: 8 }}>
            <Text style={styles.muted}>
              {ru ? "Мировая нормаль открываемой грани" : "World normal of the face to open"}
            </Text>
            <View style={styles.row}>
              {(["x", "y", "z"] as const).map((value) => (
                <Pressable
                  key={value}
                  style={[styles.chip, axis === value && { borderColor: colors.accent }]}
                  disabled={busy}
                  onPress={() => setAxis(value)}
                >
                  <Text style={styles.chipText}>{value.toUpperCase()}</Text>
                </Pressable>
              ))}
              {(["+", "-"] as const).map((value) => (
                <Pressable
                  key={value}
                  style={[styles.chip, sign === value && { borderColor: colors.accent }]}
                  disabled={busy}
                  onPress={() => setSign(value)}
                >
                  <Text style={styles.chipText}>{value}</Text>
                </Pressable>
              ))}
            </View>
            <Text style={styles.sectionSubtitle}>
              {ru
                ? "Выбирается крайняя плоская грань с указанным направлением, как в web Studio."
                : "Selects the outer planar face with that direction, matching web Studio."}
            </Text>
          </View>
        ) : null}
        {result.issue ? (
          <Text style={styles.error}>
            {ru
              ? `Толщина должна быть конечным числом от 0 до ${MAX_EXACT_DETAIL_MM} мм.`
              : `Thickness must be a finite number in (0, ${MAX_EXACT_DETAIL_MM}] mm.`}
          </Text>
        ) : null}
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
              const opened = result.spec.open_face;
              onApply(
                result.spec,
                opened
                  ? `Shell ${result.spec.thickness_mm} mm open ${opened.axis}${opened.sign}`
                  : `Shell ${result.spec.thickness_mm} mm`,
              );
            }}
          >
            <Text style={styles.buttonText}>
              {busy
                ? ru
                  ? "Создаём…"
                  : "Creating…"
                : ru
                  ? "Создать оболочку"
                  : "Create shell"}
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
