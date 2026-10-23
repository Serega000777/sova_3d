import { useMemo, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { SheetShell } from "./SheetShell";
import {
  dimensionedDrawingNumber,
  type DimensionedDrawingTrace,
  parseDimensionedDrawingHoles,
} from "./dimensioned-drawing";
import { colors, styles } from "./theme";

export type { DimensionedDrawingTrace } from "./dimensioned-drawing";

export function DimensionedDrawingSheet({
  visible,
  busy,
  calibrated,
  onClose,
  onApply,
}: {
  visible: boolean;
  busy: boolean;
  calibrated: boolean;
  onClose: () => void;
  onApply: (trace: DimensionedDrawingTrace) => void;
}) {
  const [width, setWidth] = useState("100");
  const [height, setHeight] = useState("60");
  const [thickness, setThickness] = useState("8");
  const [radius, setRadius] = useState("10");
  const [holesText, setHolesText] = useState("-25, 0, Ø10\n25, 0, Ø8");

  const result = useMemo(() => {
    const trace: DimensionedDrawingTrace = {
      width_mm: dimensionedDrawingNumber(width),
      height_mm: dimensionedDrawingNumber(height),
      thickness_mm: dimensionedDrawingNumber(thickness),
      corner_radius_mm: dimensionedDrawingNumber(radius),
      holes: parseDimensionedDrawingHoles(holesText) ?? [],
    };
    if (!parseDimensionedDrawingHoles(holesText)) {
      return { trace, issue: "Отверстия: одна строка X, Y, Ø; максимум 32." };
    }
    if (![trace.width_mm, trace.height_mm, trace.thickness_mm].every((value) => value > 0)) {
      return { trace, issue: "Ширина, высота и толщина должны быть больше нуля." };
    }
    if (trace.corner_radius_mm < 0 || trace.corner_radius_mm >= Math.min(trace.width_mm, trace.height_mm) / 2) {
      return { trace, issue: "Радиус должен быть неотрицательным и меньше половины короткой стороны." };
    }
    if (trace.holes.some((hole) => hole.diameter_mm <= 0)) {
      return { trace, issue: "Диаметр каждого отверстия должен быть больше нуля." };
    }
    return { trace, issue: null };
  }, [height, holesText, radius, thickness, width]);

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="92%"
      tabletWidth={560}
      accessibilityLabel="Закрыть трассировку размерного чертежа"
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.heading}>Точная деталь по чертежу</Text>
        <Pressable accessibilityLabel="Закрыть" onPress={onClose} hitSlop={12}>
          <Text style={[styles.title, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>
      <Text style={styles.muted}>
        Изображение остаётся source reference. Введите только явно проставленные размеры:
        сервер построит exact B-Rep, не будет угадывать геометрию по пикселям.
      </Text>
      <ScrollView contentContainerStyle={{ gap: 12 }} keyboardShouldPersistTaps="handled">
        <View style={[styles.card, { gap: 8 }]}>
          <Text style={styles.text}>Внешний контур, мм</Text>
          <View style={[styles.row, { flexWrap: "wrap" }]}>
            {[
              ["Ширина", width, setWidth],
              ["Высота", height, setHeight],
              ["Толщина", thickness, setThickness],
              ["Радиус R", radius, setRadius],
            ].map(([label, value, setValue]) => (
              <View key={label as string} style={{ minWidth: 110, flex: 1, gap: 4 }}>
                <Text style={styles.muted}>{label as string}</Text>
                <TextInput
                  style={styles.input}
                  keyboardType="decimal-pad"
                  value={value as string}
                  onChangeText={setValue as (next: string) => void}
                />
              </View>
            ))}
          </View>
        </View>
        <View style={[styles.card, { gap: 8 }]}>
          <Text style={styles.text}>Сквозные отверстия</Text>
          <Text style={styles.muted}>Одна строка: X от центра, Y от центра, Ø в мм.</Text>
          <TextInput
            accessibilityLabel="Координаты и диаметры отверстий"
            style={[styles.input, styles.mono, { minHeight: 110, textAlignVertical: "top" }]}
            multiline
            keyboardType="numbers-and-punctuation"
            value={holesText}
            onChangeText={setHolesText}
          />
        </View>
        {!calibrated && (
          <Text style={styles.error}>
            Сначала добавьте чертёж в «Фото ↔ Модель», отметьте две точки и задайте известное расстояние.
          </Text>
        )}
        {result.issue && <Text style={styles.error}>{result.issue}</Text>}
        <Pressable
          accessibilityRole="button"
          style={[styles.button, styles.buttonPrimary, (!calibrated || result.issue || busy) && { opacity: 0.5 }]}
          disabled={!calibrated || Boolean(result.issue) || busy}
          onPress={() => onApply(result.trace)}
        >
          <Text style={styles.buttonText}>{busy ? "Строим точную версию…" : "Построить CAD-деталь"}</Text>
        </Pressable>
        <Text style={styles.muted}>
          Отверстия вне контура, пересечения, недопустимый R и несогласованные размеры сервер отклонит.
        </Text>
      </ScrollView>
    </SheetShell>
  );
}
