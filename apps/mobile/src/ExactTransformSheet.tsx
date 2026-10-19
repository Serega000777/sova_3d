import type { Axis, Vec3 } from "@physical-ai/contracts";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

type Mode = "move" | "rotate" | "scale";
type ScaleAxis = "all" | Axis;
type Bounds = { x: number; y: number; z: number };

export type ExactTransformOperation =
  | { type: "translate"; offset_mm: Vec3 }
  | { type: "rotate"; axis: Axis; angle_deg: number; origin_mm: Vec3 }
  | { type: "set_dimensions"; width_mm?: number; depth_mm?: number; height_mm?: number };

function decimal(value: string): number | null {
  const parsed = Number(value.trim().replace(",", "."));
  return value.trim() && Number.isFinite(parsed) ? parsed : null;
}

export function ExactTransformSheet({
  visible,
  language,
  busy,
  bounds,
  blockedReason,
  error,
  onClose,
  onApply,
}: {
  visible: boolean;
  language: "ru" | "en";
  busy: boolean;
  bounds: Bounds | null;
  blockedReason: string | null;
  error: string | null;
  onClose: () => void;
  onApply: (operation: ExactTransformOperation, label: string) => void;
}) {
  const ru = language === "ru";
  const [mode, setMode] = useState<Mode>("move");
  const [offsets, setOffsets] = useState<[string, string, string]>(["0", "0", "0"]);
  const [rotateAxis, setRotateAxis] = useState<Axis>("z");
  const [angle, setAngle] = useState("90");
  const [scaleAxis, setScaleAxis] = useState<ScaleAxis>("all");
  const [percent, setPercent] = useState("100");

  const result = useMemo(() => {
    if (mode === "move") {
      const values = offsets.map(decimal);
      if (values.some((value) => value === null)) return null;
      const offset = values as Vec3;
      return {
        operation: { type: "translate", offset_mm: offset } as const,
        label: `Move ${offset.join(", ")} mm`,
      };
    }
    if (mode === "rotate") {
      const degrees = decimal(angle);
      if (degrees === null) return null;
      return {
        operation: {
          type: "rotate",
          axis: rotateAxis,
          angle_deg: degrees,
          origin_mm: [0, 0, 0] as Vec3,
        } as const,
        label: `Rotate ${degrees}° around ${rotateAxis.toUpperCase()}`,
      };
    }
    const value = decimal(percent);
    if (value === null || value <= 0 || !bounds) return null;
    const factor = value / 100;
    const dimensions = {
      ...(scaleAxis === "all" || scaleAxis === "x" ? { width_mm: bounds.x * factor } : {}),
      ...(scaleAxis === "all" || scaleAxis === "y" ? { depth_mm: bounds.y * factor } : {}),
      ...(scaleAxis === "all" || scaleAxis === "z" ? { height_mm: bounds.z * factor } : {}),
    };
    return {
      operation: { type: "set_dimensions", ...dimensions } as const,
      label: `Scale ${scaleAxis.toUpperCase()} to ${value}%`,
    };
  }, [angle, bounds, mode, offsets, percent, rotateAxis, scaleAxis]);

  const setOffset = (index: number, value: string) =>
    setOffsets(
      (current) =>
        current.map((item, itemIndex) => itemIndex === index ? value : item) as [
          string,
          string,
          string,
        ],
    );
  const axes = ["x", "y", "z"] as const;

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="80%"
      tabletWidth={520}
      accessibilityLabel={ru ? "Закрыть точное преобразование" : "Close exact transform"}
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.heading}>{ru ? "Точное преобразование" : "Exact transform"}</Text>
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
      <ScrollView contentContainerStyle={{ gap: 12 }} keyboardShouldPersistTaps="handled">
        <View style={styles.row}>
          {(["move", "rotate", "scale"] as const).map((item) => (
            <Pressable
              key={item}
              style={[styles.chip, mode === item && { borderColor: colors.accent }]}
              onPress={() => setMode(item)}
            >
              <Text style={[styles.chipText, mode === item && { color: colors.accent }]}>
                {item === "move"
                  ? ru ? "Переместить" : "Move"
                  : item === "rotate"
                    ? ru ? "Повернуть" : "Rotate"
                    : ru ? "Масштаб" : "Scale"}
              </Text>
            </Pressable>
          ))}
        </View>
        {mode === "move" ? (
          <>
            <Text style={styles.muted}>{ru ? "Смещение, мм" : "Offset, mm"}</Text>
            <View style={styles.row}>
              {offsets.map((value, index) => (
                <View key={axes[index]} style={{ width: 100, gap: 4 }}>
                  <Text style={styles.muted}>{axes[index].toUpperCase()}</Text>
                  <TextInput
                    style={styles.input}
                    value={value}
                    onChangeText={(next) => setOffset(index, next)}
                    keyboardType="decimal-pad"
                    selectTextOnFocus
                  />
                </View>
              ))}
            </View>
          </>
        ) : null}
        {mode === "rotate" ? (
          <>
            <Text style={styles.muted}>{ru ? "Ось вращения" : "Rotation axis"}</Text>
            <View style={styles.row}>
              {axes.map((axis) => (
                <Pressable
                  key={axis}
                  style={[styles.chip, rotateAxis === axis && { borderColor: colors.selection }]}
                  onPress={() => setRotateAxis(axis)}
                >
                  <Text style={[styles.chipText, rotateAxis === axis && { color: colors.selection }]}>{axis.toUpperCase()}</Text>
                </Pressable>
              ))}
            </View>
            <View style={{ width: 180, gap: 4 }}>
              <Text style={styles.muted}>{ru ? "Угол, градусы" : "Angle, degrees"}</Text>
              <TextInput style={styles.input} value={angle} onChangeText={setAngle} keyboardType="decimal-pad" selectTextOnFocus />
            </View>
          </>
        ) : null}
        {mode === "scale" ? (
          <>
            <Text style={styles.muted}>{ru ? "Масштабировать" : "Scale along"}</Text>
            <View style={styles.row}>
              {(["all", ...axes] as const).map((axis) => (
                <Pressable
                  key={axis}
                  style={[styles.chip, scaleAxis === axis && { borderColor: colors.selection }]}
                  onPress={() => setScaleAxis(axis)}
                >
                  <Text style={[styles.chipText, scaleAxis === axis && { color: colors.selection }]}>{axis === "all" ? (ru ? "Все оси" : "All axes") : axis.toUpperCase()}</Text>
                </Pressable>
              ))}
            </View>
            <View style={{ width: 180, gap: 4 }}>
              <Text style={styles.muted}>{ru ? "Размер, %" : "Size, %"}</Text>
              <TextInput style={styles.input} value={percent} onChangeText={setPercent} keyboardType="decimal-pad" selectTextOnFocus />
            </View>
          </>
        ) : null}
        {!result ? (
          <Text style={styles.error}>
            {mode === "scale" && !bounds
              ? ru ? "Габариты модели ещё не определены." : "Model bounds are not available yet."
              : mode === "scale"
                ? ru ? "Масштаб должен быть конечным числом больше 0%." : "Scale must be a finite number greater than 0%."
                : ru ? "Все значения должны быть конечными числами." : "All values must be finite numbers."}
          </Text>
        ) : null}
        {blockedReason ? <Text style={styles.error}>{blockedReason}</Text> : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <View style={styles.row}>
          <Pressable
            style={[styles.button, styles.buttonPrimary, (!result || blockedReason || busy) && { opacity: 0.45 }]}
            disabled={!result || Boolean(blockedReason) || busy}
            onPress={() => result && onApply(result.operation, result.label)}
          >
            <Text style={styles.buttonText}>
              {busy
                ? ru ? "Применяем…" : "Applying…"
                : mode === "move"
                  ? ru ? "Переместить" : "Move"
                  : mode === "rotate"
                    ? ru ? "Повернуть" : "Rotate"
                    : ru ? "Применить масштаб" : "Apply scale"}
            </Text>
          </Pressable>
          <Pressable style={styles.button} disabled={busy} onPress={onClose}>
            <Text style={styles.buttonText}>{ru ? "Отмена" : "Cancel"}</Text>
          </Pressable>
        </View>
        <Text style={styles.muted}>
          {ru
            ? "Масштаб сохраняет минимальный угол габарита на месте. Pivot вращения — [0, 0, 0]."
            : "Scale keeps the minimum bounds corner in place. Rotation pivot is [0, 0, 0]."}
        </Text>
      </ScrollView>
    </SheetShell>
  );
}
