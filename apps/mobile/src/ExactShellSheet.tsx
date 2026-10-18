import {
  MAX_EXACT_DETAIL_MM,
  shellSpec,
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
  const result = useMemo(() => shellSpec({ thickness }), [thickness]);

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
          ? "Создаёт замкнутую полую оболочку заданной толщины. Выбор открытой грани будет добавлен отдельным шагом после явного выбора грани в 3D."
          : "Creates a closed hollow shell with the chosen wall thickness. Opening a face will follow once mobile supports explicit 3D face picking."}
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
              onApply(result.spec, `Shell ${result.spec.thickness_mm} mm`);
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
