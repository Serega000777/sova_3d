import { useMemo, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

type Kind = "box" | "cylinder" | "sphere" | "cone" | "torus";
type Axis = "x" | "y" | "z";
export type ExactPrimitiveOperation = { type: string; [key: string]: unknown };

function number(value: string): number {
  return Number(value.replace(",", "."));
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
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

export function ExactPrimitiveSheet({
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
  onApply: (operation: ExactPrimitiveOperation, combine: "add" | "cut", label: string) => void;
}) {
  const ru = language === "ru";
  const [kind, setKind] = useState<Kind>("box");
  const [combine, setCombine] = useState<"add" | "cut">("add");
  const [axis, setAxis] = useState<Axis>("z");
  const [values, setValues] = useState({
    width: "20",
    depth: "20",
    height: "20",
    diameter: "20",
    topDiameter: "0",
    outerDiameter: "30",
    tubeDiameter: "6",
    x: "0",
    y: "0",
    z: "0",
  });
  const set = (key: keyof typeof values) => (value: string) =>
    setValues((current) => ({ ...current, [key]: value }));

  const operation = useMemo<ExactPrimitiveOperation | null>(() => {
    const origin = [number(values.x), number(values.y), number(values.z)];
    const positive = (value: string) => {
      const parsed = number(value);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    };
    if (origin.some((value) => !Number.isFinite(value))) return null;
    if (kind === "box") {
      const width = positive(values.width);
      const depth = positive(values.depth);
      const height = positive(values.height);
      return width && depth && height
        ? { type: "create_box", width_mm: width, depth_mm: depth, height_mm: height, origin_mm: origin }
        : null;
    }
    if (kind === "sphere") {
      const diameter = positive(values.diameter);
      return diameter ? { type: "create_sphere", diameter_mm: diameter, origin_mm: origin } : null;
    }
    if (kind === "torus") {
      const outer = positive(values.outerDiameter);
      const tube = positive(values.tubeDiameter);
      return outer && tube && tube * 2 < outer
        ? { type: "create_torus", outer_diameter_mm: outer, tube_diameter_mm: tube, axis, origin_mm: origin }
        : null;
    }
    const diameter = positive(values.diameter);
    const height = positive(values.height);
    if (!diameter || !height) return null;
    if (kind === "cylinder") {
      return { type: "create_cylinder", diameter_mm: diameter, height_mm: height, axis, origin_mm: origin };
    }
    const top = number(values.topDiameter);
    return Number.isFinite(top) && top >= 0
      ? {
          type: "create_cone",
          bottom_diameter_mm: diameter,
          top_diameter_mm: top,
          height_mm: height,
          axis,
          origin_mm: origin,
        }
      : null;
  }, [axis, kind, values]);

  const labels: Record<Kind, string> = {
    box: ru ? "Коробка" : "Box",
    cylinder: ru ? "Цилиндр" : "Cylinder",
    sphere: ru ? "Сфера" : "Sphere",
    cone: ru ? "Конус" : "Cone",
    torus: ru ? "Тор" : "Torus",
  };

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="82%"
      tabletWidth={540}
      accessibilityLabel={ru ? "Закрыть точное тело" : "Close exact solid"}
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.heading}>{ru ? "Добавить точное тело" : "Add exact solid"}</Text>
        <Pressable onPress={onClose} hitSlop={12}>
          <Text style={[styles.title, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>
      <Text style={styles.muted}>
        {ru
          ? "Примитив строится B-Rep-ядром и добавляется либо вычитается из текущего exact body в новой версии."
          : "The B-Rep kernel builds the primitive and adds it to or subtracts it from the current exact body in a new version."}
      </Text>
      <ScrollView contentContainerStyle={{ gap: 12 }} keyboardShouldPersistTaps="handled">
        <View style={styles.row}>
          {(Object.keys(labels) as Kind[]).map((item) => (
            <Pressable
              key={item}
              style={[styles.chip, kind === item && { borderColor: colors.accent }]}
              onPress={() => setKind(item)}
            >
              <Text style={[styles.chipText, kind === item && { color: colors.accent }]}>
                {labels[item]}
              </Text>
            </Pressable>
          ))}
        </View>
        <View style={styles.row}>
          {kind === "box" ? (
            <>
              <Field label={ru ? "Ширина, мм" : "Width, mm"} value={values.width} onChange={set("width")} />
              <Field label={ru ? "Глубина, мм" : "Depth, mm"} value={values.depth} onChange={set("depth")} />
            </>
          ) : null}
          {kind === "cylinder" || kind === "sphere" || kind === "cone" ? (
            <Field label={ru ? "Диаметр, мм" : "Diameter, mm"} value={values.diameter} onChange={set("diameter")} />
          ) : null}
          {kind === "cone" ? (
            <Field label={ru ? "Верхний диаметр, мм" : "Top diameter, mm"} value={values.topDiameter} onChange={set("topDiameter")} />
          ) : null}
          {kind === "torus" ? (
            <>
              <Field label={ru ? "Внешний диаметр, мм" : "Outer diameter, mm"} value={values.outerDiameter} onChange={set("outerDiameter")} />
              <Field label={ru ? "Диаметр трубки, мм" : "Tube diameter, mm"} value={values.tubeDiameter} onChange={set("tubeDiameter")} />
            </>
          ) : null}
          {kind !== "sphere" && kind !== "torus" ? (
            <Field label={ru ? "Высота, мм" : "Height, mm"} value={values.height} onChange={set("height")} />
          ) : null}
        </View>
        {kind !== "box" && kind !== "sphere" ? (
          <View style={styles.row}>
            <Text style={styles.muted}>{ru ? "Ось" : "Axis"}</Text>
            {(["x", "y", "z"] as const).map((item) => (
              <Pressable key={item} style={[styles.chip, axis === item && { borderColor: colors.selection }]} onPress={() => setAxis(item)}>
                <Text style={[styles.chipText, axis === item && { color: colors.selection }]}>{item.toUpperCase()}</Text>
              </Pressable>
            ))}
          </View>
        ) : null}
        <Text style={styles.muted}>{ru ? "Начало X/Y/Z, мм" : "Origin X/Y/Z, mm"}</Text>
        <View style={styles.row}>
          <Field label="X" value={values.x} onChange={set("x")} />
          <Field label="Y" value={values.y} onChange={set("y")} />
          <Field label="Z" value={values.z} onChange={set("z")} />
        </View>
        <View style={styles.row}>
          {(["add", "cut"] as const).map((item) => (
            <Pressable key={item} style={[styles.chip, combine === item && { borderColor: colors.accent2 }]} onPress={() => setCombine(item)}>
              <Text style={[styles.chipText, combine === item && { color: colors.accent2 }]}>
                {item === "add" ? (ru ? "Добавить" : "Add") : ru ? "Вырезать" : "Cut"}
              </Text>
            </Pressable>
          ))}
        </View>
        {!operation ? (
          <Text style={styles.error}>
            {ru
              ? "Введите конечные положительные размеры; диаметр трубки тора должен быть меньше половины внешнего."
              : "Enter finite positive dimensions; torus tube diameter must be less than half the outer diameter."}
          </Text>
        ) : null}
        {blockedReason ? <Text style={styles.error}>{blockedReason}</Text> : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <View style={styles.row}>
          <Pressable
            style={[styles.button, styles.buttonPrimary, (!operation || blockedReason || busy) && { opacity: 0.45 }]}
            disabled={!operation || Boolean(blockedReason) || busy}
            onPress={() => operation && onApply(operation, combine, labels[kind])}
          >
            <Text style={styles.buttonText}>{busy ? (ru ? "Строим…" : "Building…") : ru ? "Применить" : "Apply"}</Text>
          </Pressable>
          <Pressable style={styles.button} disabled={busy} onPress={onClose}>
            <Text style={styles.buttonText}>{ru ? "Отмена" : "Cancel"}</Text>
          </Pressable>
        </View>
      </ScrollView>
    </SheetShell>
  );
}
