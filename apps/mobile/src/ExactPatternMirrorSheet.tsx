import {
  circularPatternSpec,
  linearPatternSpec,
  MAX_EXACT_DETAIL_MM,
  mirrorSpec,
  type Axis,
  type ExactCircularPatternSpec,
  type ExactLinearPatternSpec,
  type ExactMirrorSpec,
} from "@physical-ai/contracts";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

type OperationMode = "linear" | "circular" | "mirror";

export function ExactPatternMirrorSheet({
  visible,
  language,
  busy,
  blockedReason,
  error,
  onClose,
  onApplyLinearPattern,
  onApplyCircularPattern,
  onApplyMirror,
}: {
  visible: boolean;
  language: "ru" | "en";
  busy: boolean;
  blockedReason: string | null;
  error: string | null;
  onClose: () => void;
  onApplyLinearPattern: (spec: ExactLinearPatternSpec, label: string) => void;
  onApplyCircularPattern: (spec: ExactCircularPatternSpec, label: string) => void;
  onApplyMirror: (spec: ExactMirrorSpec, label: string) => void;
}) {
  const ru = language === "ru";
  const [operationMode, setOperationMode] = useState<OperationMode>("linear");
  const [axis, setAxis] = useState<Axis>("x");
  const [count, setCount] = useState("2");
  const [spacing, setSpacing] = useState("10");
  const [angle, setAngle] = useState("360");
  const [originX, setOriginX] = useState("0");
  const [originY, setOriginY] = useState("0");
  const [originZ, setOriginZ] = useState("0");
  const [offset, setOffset] = useState("0");
  const [keepOriginal, setKeepOriginal] = useState(true);

  const linearResult = useMemo(
    () => linearPatternSpec({ axis, count, spacing }),
    [axis, count, spacing],
  );
  const circularResult = useMemo(
    () => circularPatternSpec({ axis, count, angle, originX, originY, originZ }),
    [angle, axis, count, originX, originY, originZ],
  );
  const mirrorResult = useMemo(
    () => mirrorSpec({ axis, offset, keepOriginal }),
    [axis, keepOriginal, offset],
  );
  const activeResult =
    operationMode === "linear"
      ? linearResult
      : operationMode === "circular"
        ? circularResult
        : mirrorResult;

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="84%"
      tabletWidth={520}
      accessibilityLabel={ru ? "Закрыть массивы и зеркало" : "Close patterns and mirror"}
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.heading}>{ru ? "Массивы + зеркало" : "Patterns + mirror"}</Text>
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
          ? "Операция применяется к текущему точному телу по символьным параметрам. Явный выбор тела или грани в 3D пока не используется, как и в web Studio."
          : "The operation targets the current exact body through symbolic parameters. Explicit 3D body or face picking is not used yet, matching web Studio."}
      </Text>
      <ScrollView contentContainerStyle={{ gap: 12 }} keyboardShouldPersistTaps="handled">
        <Text style={styles.muted}>{ru ? "Операция" : "Operation"}</Text>
        <View style={styles.row}>
          {(
            [
              ["linear", ru ? "Линейный массив" : "Linear pattern"],
              ["circular", ru ? "Круговой массив" : "Circular pattern"],
              ["mirror", ru ? "Зеркало" : "Mirror"],
            ] as const
          ).map(([item, label]) => (
            <Pressable
              key={item}
              style={[styles.chip, operationMode === item && { borderColor: colors.accent }]}
              onPress={() => setOperationMode(item)}
            >
              <Text
                style={[styles.chipText, operationMode === item && { color: colors.accent }]}
              >
                {label}
              </Text>
            </Pressable>
          ))}
        </View>

        <Text style={styles.muted}>
          {operationMode === "mirror"
            ? ru
              ? "Нормаль плоскости"
              : "Plane normal"
            : ru
              ? "Ось"
              : "Axis"}
        </Text>
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
        </View>

        {operationMode !== "mirror" ? (
          <View style={{ width: 180, gap: 4 }}>
            <Text style={styles.muted}>{ru ? "Количество (2–100)" : "Count (2–100)"}</Text>
            <TextInput
              style={styles.input}
              value={count}
              onChangeText={setCount}
              keyboardType="number-pad"
              selectTextOnFocus
            />
          </View>
        ) : null}

        {operationMode === "linear" ? (
          <View style={{ width: 180, gap: 4 }}>
            <Text style={styles.muted}>{ru ? "Шаг, мм" : "Spacing, mm"}</Text>
            <TextInput
              style={styles.input}
              value={spacing}
              onChangeText={setSpacing}
              keyboardType="decimal-pad"
              selectTextOnFocus
            />
          </View>
        ) : null}

        {operationMode === "circular" ? (
          <>
            <View style={{ width: 180, gap: 4 }}>
              <Text style={styles.muted}>{ru ? "Угол, °" : "Angle, °"}</Text>
              <TextInput
                style={styles.input}
                value={angle}
                onChangeText={setAngle}
                keyboardType="decimal-pad"
                selectTextOnFocus
              />
            </View>
            <Text style={styles.muted}>{ru ? "Центр вращения, мм" : "Rotation origin, mm"}</Text>
            <View style={styles.row}>
              {(
                [
                  ["X", originX, setOriginX],
                  ["Y", originY, setOriginY],
                  ["Z", originZ, setOriginZ],
                ] as const
              ).map(([label, value, setter]) => (
                <View key={label} style={{ width: 100, gap: 4 }}>
                  <Text style={styles.muted}>{label}</Text>
                  <TextInput
                    style={styles.input}
                    value={value}
                    onChangeText={setter}
                    keyboardType="decimal-pad"
                    selectTextOnFocus
                  />
                </View>
              ))}
            </View>
          </>
        ) : null}

        {operationMode === "mirror" ? (
          <>
            <View style={{ width: 180, gap: 4 }}>
              <Text style={styles.muted}>{ru ? "Смещение плоскости, мм" : "Plane offset, mm"}</Text>
              <TextInput
                style={styles.input}
                value={offset}
                onChangeText={setOffset}
                keyboardType="decimal-pad"
                selectTextOnFocus
              />
            </View>
            <View style={[styles.row, { justifyContent: "space-between" }]}>
              <Text style={styles.muted}>{ru ? "Сохранить исходное тело" : "Keep original body"}</Text>
              <Switch
                value={keepOriginal}
                disabled={busy}
                onValueChange={setKeepOriginal}
                trackColor={{ false: colors.border, true: colors.accent2 }}
              />
            </View>
          </>
        ) : null}

        {activeResult.issue === "invalid_axis" ? (
          <Text style={styles.error}>{ru ? "Выберите ось X, Y или Z." : "Choose axis X, Y, or Z."}</Text>
        ) : null}
        {activeResult.issue === "invalid_count" ? (
          <Text style={styles.error}>
            {ru ? "Количество должно быть целым числом от 2 до 100." : "Count must be an integer from 2 to 100."}
          </Text>
        ) : null}
        {activeResult.issue === "invalid_spacing" ? (
          <Text style={styles.error}>
            {ru
              ? `Шаг должен быть конечным числом в диапазоне (0, ${MAX_EXACT_DETAIL_MM}] мм.`
              : `Spacing must be a finite number in (0, ${MAX_EXACT_DETAIL_MM}] mm.`}
          </Text>
        ) : null}
        {activeResult.issue === "invalid_angle" ? (
          <Text style={styles.error}>
            {ru ? "Угол должен быть конечным числом в диапазоне (0, 360]°." : "Angle must be a finite number in (0, 360]°."}
          </Text>
        ) : null}
        {activeResult.issue === "invalid_origin" ? (
          <Text style={styles.error}>
            {ru ? "Все координаты центра должны быть конечными числами." : "All origin coordinates must be finite numbers."}
          </Text>
        ) : null}
        {activeResult.issue === "invalid_offset" ? (
          <Text style={styles.error}>
            {ru
              ? `Смещение должно быть конечным числом от -${MAX_EXACT_DETAIL_MM} до ${MAX_EXACT_DETAIL_MM} мм.`
              : `Offset must be a finite number from -${MAX_EXACT_DETAIL_MM} to ${MAX_EXACT_DETAIL_MM} mm.`}
          </Text>
        ) : null}
        {blockedReason ? <Text style={styles.error}>{blockedReason}</Text> : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}

        <View style={styles.row}>
          <Pressable
            style={[
              styles.button,
              styles.buttonPrimary,
              (!activeResult.spec || blockedReason || busy) && { opacity: 0.45 },
            ]}
            disabled={!activeResult.spec || Boolean(blockedReason) || busy}
            onPress={() => {
              if (operationMode === "linear") {
                if (!linearResult.spec) return;
                onApplyLinearPattern(
                  linearResult.spec,
                  `Linear pattern ×${linearResult.spec.count} / ${linearResult.spec.spacing_mm} mm`,
                );
                return;
              }
              if (operationMode === "circular") {
                if (!circularResult.spec) return;
                onApplyCircularPattern(
                  circularResult.spec,
                  `Circular pattern ×${circularResult.spec.count} / ${circularResult.spec.angle_deg}°`,
                );
                return;
              }
              if (!mirrorResult.spec) return;
              onApplyMirror(
                mirrorResult.spec,
                `Mirror ${mirrorResult.spec.axis.toUpperCase()} / ${mirrorResult.spec.offset_mm} mm`,
              );
            }}
          >
            <Text style={styles.buttonText}>
              {busy
                ? ru
                  ? "Создаём…"
                  : "Creating…"
                : operationMode === "linear"
                  ? ru
                    ? "Создать линейный массив"
                    : "Create linear pattern"
                  : operationMode === "circular"
                    ? ru
                      ? "Создать круговой массив"
                      : "Create circular pattern"
                    : ru
                      ? "Создать зеркало"
                      : "Create mirror"}
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
