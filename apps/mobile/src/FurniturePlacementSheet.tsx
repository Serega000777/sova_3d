import type { FurnitureItem, Vec3 } from "@physical-ai/contracts";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

type FurnitureKind = FurnitureItem["kind"];

export function FurniturePlacementSheet({
  visible,
  language,
  items,
  kind,
  point,
  rotation,
  busy,
  onClose,
  onKindChange,
  onPointChange,
  onRotationChange,
  onPickPoint,
  onApply,
}: {
  visible: boolean;
  language: "ru" | "en";
  items: FurnitureItem[];
  kind: FurnitureKind;
  point: Vec3;
  rotation: number;
  busy: boolean;
  onClose: () => void;
  onKindChange: (kind: FurnitureKind) => void;
  onPointChange: (point: Vec3) => void;
  onRotationChange: (degrees: number) => void;
  onPickPoint: () => void;
  onApply: () => void;
}) {
  const ru = language === "ru";
  const [draft, setDraft] = useState(() => point.map(String) as [string, string, string]);

  useEffect(() => setDraft(point.map((value) => value.toFixed(1)) as [string, string, string]), [point]);

  const updateAxis = (axis: 0 | 1 | 2, value: string) => {
    const next = [...draft] as [string, string, string];
    next[axis] = value;
    setDraft(next);
    const number = Number(value.replace(",", "."));
    if (!Number.isFinite(number)) return;
    const nextPoint = [...point] as Vec3;
    nextPoint[axis] = number;
    onPointChange(nextPoint);
  };
  const selected = items.find((item) => item.kind === kind);

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="62%"
      accessibilityLabel={ru ? "Закрыть расстановку мебели" : "Close furniture placement"}
    >
      <View style={{ gap: 12 }}>
        <View style={[styles.row, { justifyContent: "space-between" }]}>
          <Text style={styles.heading}>{ru ? "Мебель в масштабе" : "Real-scale furniture"}</Text>
          <Pressable style={styles.chip} onPress={onClose} hitSlop={12}>
            <Text style={styles.chipText}>×</Text>
          </Pressable>
        </View>
        <Text style={styles.muted}>
          {ru
            ? "Выберите предмет, затем точку на полу в 3D. Оранжевая точка — точная позиция новой immutable-версии."
            : "Choose an item, then a floor point in 3D. The orange point is the exact position for a new immutable version."}
        </Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
          {items.map((item) => (
            <Pressable
              key={item.kind}
              style={[styles.card, { minWidth: 132, gap: 3 }, item.kind === kind && { borderColor: colors.accent }]}
              onPress={() => onKindChange(item.kind)}
            >
              <Text style={[styles.text, item.kind === kind && { color: colors.accent }]}>
                {ru ? item.name_ru : item.name}
              </Text>
              <Text style={styles.muted}>
                {item.width_mm} × {item.depth_mm} × {item.height_mm} mm
              </Text>
            </Pressable>
          ))}
        </ScrollView>
        {items.length === 0 ? <Text style={styles.muted}>{ru ? "Загружаем каталог…" : "Loading catalogue…"}</Text> : null}
        <View style={styles.row}>
          {(["X", "Y", "Z"] as const).map((label, axis) => (
            <View key={label} style={{ flex: 1, gap: 4 }}>
              <Text style={styles.muted}>{label}, mm</Text>
              <TextInput
                style={styles.input}
                keyboardType="decimal-pad"
                value={draft[axis]}
                onChangeText={(value) => updateAxis(axis as 0 | 1 | 2, value)}
              />
            </View>
          ))}
        </View>
        <View style={styles.row}>
          {[-90, -15, 15, 90].map((delta) => (
            <Pressable key={delta} style={styles.chip} onPress={() => onRotationChange(rotation + delta)}>
              <Text style={styles.chipText}>{delta > 0 ? "+" : ""}{delta}°</Text>
            </Pressable>
          ))}
          <Text style={[styles.text, { color: colors.accent }]}>{rotation.toFixed(0)}°</Text>
        </View>
        <Pressable style={styles.button} onPress={onPickPoint}>
          <Text style={styles.buttonText}>{ru ? "Указать точку касанием в 3D" : "Pick a point by touch in 3D"}</Text>
        </Pressable>
        <Pressable
          style={[styles.button, styles.buttonPrimary, (!selected || busy) && { opacity: 0.5 }]}
          disabled={!selected || busy}
          onPress={onApply}
        >
          <Text style={styles.buttonText}>
            {busy ? (ru ? "Добавляем…" : "Adding…") : ru ? "Добавить в новую версию" : "Add in a new version"}
          </Text>
        </Pressable>
      </View>
    </SheetShell>
  );
}
