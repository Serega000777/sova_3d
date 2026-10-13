import type { MeshEditReport, SurfaceDetailOperation, Vec3 } from "@physical-ai/contracts";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

type Language = "ru" | "en";
type Shape = "circle" | "square" | "ribs" | "knurl";

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
    <View style={{ width: 132, gap: 4 }}>
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

function numeric(value: string): number {
  return Number(value.replace(",", "."));
}

export function SurfaceDetailSheet({
  visible,
  language,
  anchor,
  busy,
  previewTriangles,
  report,
  error,
  onClose,
  onRun,
  onClearPreview,
}: {
  visible: boolean;
  language: Language;
  anchor: { at_mm: Vec3; normal: Vec3 } | null;
  busy: boolean;
  previewTriangles: number | null;
  report: MeshEditReport | null;
  error: string | null;
  onClose: () => void;
  onRun: (operation: SurfaceDetailOperation, preview: boolean) => void;
  onClearPreview: () => void;
}) {
  const ru = language === "ru";
  const [shape, setShape] = useState<Shape>("circle");
  const [mode, setMode] = useState<"raised" | "recessed">("raised");
  const [pattern, setPattern] = useState<"straight" | "diamond">("diamond");
  const [values, setValues] = useState({
    diameter: "6",
    width: "6",
    height: "6",
    rotation: "0",
    areaWidth: "10",
    areaLength: "10",
    pitch: "2",
    ribWidth: "1",
    angle: "45",
    depth: "1",
  });

  const setValue = (key: keyof typeof values) => (value: string) => {
    setValues((current) => ({ ...current, [key]: value }));
    onClearPreview();
  };

  const operation = useMemo<SurfaceDetailOperation | null>(() => {
    if (!anchor) return null;
    const depth = numeric(values.depth);
    const positive = (value: string) => {
      const parsed = numeric(value);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    };
    if (!Number.isFinite(depth) || depth <= 0) return null;
    let profile: SurfaceDetailOperation["profile"];
    if (shape === "circle") {
      const diameter = positive(values.diameter);
      if (diameter == null) return null;
      profile = { shape, diameter_mm: diameter };
    } else if (shape === "square") {
      const width = positive(values.width);
      const height = positive(values.height);
      const rotation = numeric(values.rotation);
      if (width == null || height == null || !Number.isFinite(rotation)) return null;
      profile = { shape, width_mm: width, height_mm: height, rotation_deg: rotation };
    } else {
      const width = positive(values.areaWidth);
      const length = positive(values.areaLength);
      const pitch = positive(values.pitch);
      const rotation = numeric(values.rotation);
      if (width == null || length == null || pitch == null || !Number.isFinite(rotation)) {
        return null;
      }
      const area = { width_mm: width, length_mm: length, rotation_deg: rotation };
      if (shape === "ribs") {
        const ribWidth = positive(values.ribWidth);
        if (ribWidth == null || ribWidth >= pitch) return null;
        profile = { shape, area, pitch_mm: pitch, rib_width_mm: ribWidth, angle_deg: 0 };
      } else {
        const angle = numeric(values.angle);
        if (
          !Number.isFinite(angle) ||
          (pattern === "diamond" && (Math.abs(angle) < 5 || Math.abs(angle) > 85))
        ) {
          return null;
        }
        profile = { shape, area, pattern, pitch_mm: pitch, angle_deg: angle };
      }
    }
    return {
      op: "detail",
      at_mm: anchor.at_mm,
      normal_hint: anchor.normal,
      profile,
      mode,
      depth_mm: depth,
    };
  }, [anchor, mode, pattern, shape, values]);

  const chooseShape = (next: Shape) => {
    setShape(next);
    onClearPreview();
  };
  const chooseMode = (next: "raised" | "recessed") => {
    setMode(next);
    onClearPreview();
  };

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="82%"
      tabletWidth={520}
      accessibilityLabel={ru ? "Закрыть деталь поверхности" : "Close surface detail"}
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.heading}>{ru ? "Деталь на поверхности" : "Surface detail"}</Text>
        <Pressable onPress={onClose} hitSlop={12}>
          <Text style={[styles.title, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>
      <Text style={styles.muted}>
        {ru
          ? "Точно по центру одной выбранной грани. Сначала проверьте контур, затем примените."
          : "Centred exactly on one selected face. Preview the footprint before applying."}
      </Text>
      <ScrollView contentContainerStyle={{ gap: 12 }} keyboardShouldPersistTaps="handled">
        <View style={styles.row}>
          {(["circle", "square", "ribs", "knurl"] as const).map((item) => (
            <Pressable
              key={item}
              style={[styles.chip, shape === item && { borderColor: colors.accent }]}
              onPress={() => chooseShape(item)}
            >
              <Text style={[styles.chipText, shape === item && { color: colors.accent }]}>
                {{ circle: ru ? "Круг" : "Circle", square: ru ? "Квадрат" : "Square", ribs: ru ? "Рёбра" : "Ribs", knurl: ru ? "Накатка" : "Knurl" }[item]}
              </Text>
            </Pressable>
          ))}
        </View>
        <View style={styles.row}>
          {(["raised", "recessed"] as const).map((item) => (
            <Pressable
              key={item}
              style={[styles.chip, mode === item && { borderColor: colors.selection }]}
              onPress={() => chooseMode(item)}
            >
              <Text style={[styles.chipText, mode === item && { color: colors.selection }]}>
                {item === "raised" ? (ru ? "Выступ" : "Raised") : ru ? "Выемка" : "Recessed"}
              </Text>
            </Pressable>
          ))}
        </View>
        <View style={styles.row}>
          {shape === "circle" ? (
            <Field label={ru ? "Диаметр, мм" : "Diameter, mm"} value={values.diameter} onChange={setValue("diameter")} />
          ) : null}
          {shape === "square" ? (
            <>
              <Field label={ru ? "Ширина, мм" : "Width, mm"} value={values.width} onChange={setValue("width")} />
              <Field label={ru ? "Высота, мм" : "Height, mm"} value={values.height} onChange={setValue("height")} />
            </>
          ) : null}
          {shape === "ribs" || shape === "knurl" ? (
            <>
              <Field label={ru ? "Ширина области, мм" : "Area width, mm"} value={values.areaWidth} onChange={setValue("areaWidth")} />
              <Field label={ru ? "Длина области, мм" : "Area length, mm"} value={values.areaLength} onChange={setValue("areaLength")} />
              <Field label={ru ? "Шаг, мм" : "Pitch, mm"} value={values.pitch} onChange={setValue("pitch")} />
            </>
          ) : null}
          {shape === "ribs" ? (
            <Field label={ru ? "Ширина ребра, мм" : "Rib width, mm"} value={values.ribWidth} onChange={setValue("ribWidth")} />
          ) : null}
          {shape === "knurl" ? (
            <Field label={ru ? "Угол, °" : "Angle, °"} value={values.angle} onChange={setValue("angle")} />
          ) : null}
          {shape !== "circle" ? (
            <Field label={ru ? "Поворот области, °" : "Area rotation, °"} value={values.rotation} onChange={setValue("rotation")} />
          ) : null}
          <Field label={ru ? "Глубина, мм" : "Depth, mm"} value={values.depth} onChange={setValue("depth")} />
        </View>
        {shape === "knurl" ? (
          <View style={styles.row}>
            {(["diamond", "straight"] as const).map((item) => (
              <Pressable
                key={item}
                style={[styles.chip, pattern === item && { borderColor: colors.selection }]}
                onPress={() => {
                  setPattern(item);
                  onClearPreview();
                }}
              >
                <Text style={[styles.chipText, pattern === item && { color: colors.selection }]}>
                  {item === "diamond" ? (ru ? "Ромб" : "Diamond") : ru ? "Прямая" : "Straight"}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : null}
        {!operation ? (
          <Text style={styles.error}>
            {ru
              ? "Введите конечные положительные размеры; ширина ребра должна быть меньше шага, угол ромбической накатки — от 5° до 85°."
              : "Enter finite positive dimensions; rib width must be smaller than pitch and diamond angle must be 5–85°."}
          </Text>
        ) : null}
        {previewTriangles != null ? (
          <Text style={styles.mono}>
            {ru ? "Проверенный контур · около" : "Validated footprint · about"} {previewTriangles.toLocaleString()} {ru ? "треугольников" : "triangles"}
          </Text>
        ) : null}
        {previewTriangles != null && report?.message ? (
          <Text style={report.ok ? styles.muted : styles.error}>{report.message}</Text>
        ) : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <View style={styles.row}>
          <Pressable
            style={[styles.button, (!operation || busy) && { opacity: 0.45 }]}
            disabled={!operation || busy}
            onPress={() => operation && onRun(operation, true)}
          >
            <Text style={styles.buttonText}>{ru ? "Проверить контур" : "Preview footprint"}</Text>
          </Pressable>
          <Pressable
            style={[
              styles.button,
              styles.buttonPrimary,
              (!operation || previewTriangles == null || busy) && { opacity: 0.45 },
            ]}
            disabled={!operation || previewTriangles == null || busy}
            onPress={() => operation && onRun(operation, false)}
          >
            <Text style={styles.buttonText}>{busy ? (ru ? "Выполняем…" : "Working…") : ru ? "Применить" : "Apply"}</Text>
          </Pressable>
        </View>
      </ScrollView>
    </SheetShell>
  );
}
