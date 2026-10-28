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
  floorPlanId,
  clearance,
  busy,
  onClose,
  onKindChange,
  onPointChange,
  onRotationChange,
  onClearanceChange,
  onPickPoint,
  onDragInPlan,
  onApply,
}: {
  visible: boolean;
  language: "ru" | "en";
  items: FurnitureItem[];
  kind: FurnitureKind;
  point: Vec3;
  rotation: number;
  floorPlanId: string | null;
  clearance: number;
  busy: boolean;
  onClose: () => void;
  onKindChange: (kind: FurnitureKind) => void;
  onPointChange: (point: Vec3) => void;
  onRotationChange: (degrees: number) => void;
  onClearanceChange: (millimetres: number) => void;
  onPickPoint: () => void;
  onDragInPlan: () => void;
  onApply: () => void;
}) {
  const ru = language === "ru";
  const [draft, setDraft] = useState(() => point.map(String) as [string, string, string]);

  useEffect(() => setDraft(point.map((value) => value.toFixed(1)) as [string, string, string]), [point]);

  useEffect(() => {
    if (floorPlanId && point[2] !== 0) onPointChange([point[0], point[1], 0]);
  }, [floorPlanId, onPointChange, point]);

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
        <View style={[styles.card, { gap: 8, borderColor: floorPlanId ? colors.green : colors.yellow }]}>
          <Text style={styles.text}>
            {floorPlanId
              ? ru ? "Проверка по текущему 2D-плану" : "Validated against the current 2D plan"
              : ru ? "Без проверки по плану" : "No floor-plan validation"}
          </Text>
          <Text style={styles.muted}>
            {floorPlanId
              ? ru
                ? "Сервер не добавит предмет вне комнаты, рядом со стеной или поверх другой мебели."
                : "The server rejects placements outside a room, too close to a wall, or overlapping other furniture."
              : ru
                ? "У выбранной версии нет связанного плана; доступна только свободная 3D-позиция."
                : "The selected version has no linked plan; only unrestricted 3D placement is available."}
          </Text>
          {floorPlanId ? (
            <View style={styles.row}>
              {[0, 150, 300].map((value) => (
                <Pressable
                  key={value}
                  style={[styles.chip, clearance === value && { borderColor: colors.accent }]}
                  onPress={() => onClearanceChange(value)}
                >
                  <Text style={[styles.chipText, clearance === value && { color: colors.accent }]}>
                    {ru ? "Зазор" : "Clearance"} {value} mm
                  </Text>
                </Pressable>
              ))}
            </View>
          ) : null}
        </View>
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
                editable={!floorPlanId || axis !== 2}
                onChangeText={(value) => updateAxis(axis as 0 | 1 | 2, value)}
              />
            </View>
          ))}
        </View>
        {floorPlanId ? (
          <Text style={styles.muted}>
            {ru
              ? "Z зафиксирован на 0 мм: проверяемая расстановка относится к полу текущего одноуровневого плана."
              : "Z is fixed at 0 mm: validated placement belongs to the current single-level plan floor."}
          </Text>
        ) : null}
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
        {floorPlanId ? (
          <Pressable style={styles.button} onPress={onDragInPlan}>
            <Text style={styles.buttonText}>{ru ? "Перетащить на 2D-плане" : "Drag on the 2D plan"}</Text>
          </Pressable>
        ) : null}
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
