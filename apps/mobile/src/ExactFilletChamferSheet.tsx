import {
  chamferSpec,
  filletSpec,
  MAX_EXACT_DETAIL_MM,
  type Axis,
  type EdgeSelectorDraft,
  type ExactChamferSpec,
  type ExactFilletSpec,
} from "@physical-ai/contracts";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

type OperationMode = "fillet" | "chamfer";
type SelectorMode = EdgeSelectorDraft["kind"];

export function ExactFilletChamferSheet({
  visible,
  language,
  busy,
  blockedReason,
  error,
  onClose,
  onApplyFillet,
  onApplyChamfer,
}: {
  visible: boolean;
  language: "ru" | "en";
  busy: boolean;
  blockedReason: string | null;
  error: string | null;
  onClose: () => void;
  onApplyFillet: (spec: ExactFilletSpec, label: string) => void;
  onApplyChamfer: (spec: ExactChamferSpec, label: string) => void;
}) {
  const ru = language === "ru";
  const [operationMode, setOperationMode] = useState<OperationMode>("fillet");
  const [selectorMode, setSelectorMode] = useState<SelectorMode>("all_edges");
  const [axis, setAxis] = useState<Axis>("z");
  const [sign, setSign] = useState<"+" | "-">("+");
  const [outer, setOuter] = useState(false);
  const [radius, setRadius] = useState("2");
  const [distance, setDistance] = useState("2");

  const edges = useMemo<EdgeSelectorDraft>(() => {
    if (selectorMode === "edges_parallel_to") {
      return { kind: "edges_parallel_to", axis, outer };
    }
    if (selectorMode === "edges_of_face") {
      return { kind: "edges_of_face", axis, sign };
    }
    return { kind: "all_edges" };
  }, [axis, outer, selectorMode, sign]);
  const filletResult = useMemo(() => filletSpec({ edges, radius }), [edges, radius]);
  const chamferResult = useMemo(
    () => chamferSpec({ edges, distance }),
    [distance, edges],
  );
  const activeResult = operationMode === "fillet" ? filletResult : chamferResult;
  const dimensionIssue =
    operationMode === "fillet"
      ? filletResult.issue === "invalid_radius"
      : chamferResult.issue === "invalid_distance";

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="82%"
      tabletWidth={520}
      accessibilityLabel={
        ru ? "Закрыть скругление и фаску" : "Close fillet and chamfer"
      }
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.heading}>{ru ? "Скругление + фаска" : "Fillet + chamfer"}</Text>
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
          ? "Выберите семейство рёбер по геометрическому признаку. Явный выбор отдельного ребра в 3D пока не используется."
          : "Choose an edge family by a geometric rule. Explicit picking of an individual 3D edge is not used yet."}
      </Text>
      <ScrollView contentContainerStyle={{ gap: 12 }} keyboardShouldPersistTaps="handled">
        <Text style={styles.muted}>{ru ? "Операция" : "Operation"}</Text>
        <View style={styles.row}>
          {(["fillet", "chamfer"] as const).map((item) => (
            <Pressable
              key={item}
              style={[
                styles.chip,
                operationMode === item && { borderColor: colors.accent },
              ]}
              onPress={() => setOperationMode(item)}
            >
              <Text
                style={[
                  styles.chipText,
                  operationMode === item && { color: colors.accent },
                ]}
              >
                {item === "fillet"
                  ? ru
                    ? "Скругление"
                    : "Fillet"
                  : ru
                    ? "Фаска"
                    : "Chamfer"}
              </Text>
            </Pressable>
          ))}
        </View>

        <Text style={styles.muted}>{ru ? "Выбор рёбер" : "Edge selection"}</Text>
        <View style={styles.row}>
          {(
            [
              ["all_edges", ru ? "Все рёбра" : "All edges"],
              ["edges_parallel_to", ru ? "Параллельно оси" : "Parallel to axis"],
              ["edges_of_face", ru ? "Рёбра грани" : "Edges of face"],
            ] as const
          ).map(([item, label]) => (
            <Pressable
              key={item}
              style={[
                styles.chip,
                selectorMode === item && { borderColor: colors.selection },
              ]}
              onPress={() => setSelectorMode(item)}
            >
              <Text
                style={[
                  styles.chipText,
                  selectorMode === item && { color: colors.selection },
                ]}
              >
                {label}
              </Text>
            </Pressable>
          ))}
        </View>

        {selectorMode !== "all_edges" ? (
          <>
            <Text style={styles.muted}>
              {selectorMode === "edges_of_face"
                ? ru
                  ? "Нормаль грани"
                  : "Face normal"
                : ru
                  ? "Ось рёбер"
                  : "Edge axis"}
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
              {selectorMode === "edges_of_face"
                ? (["+", "-"] as const).map((item) => (
                    <Pressable
                      key={item}
                      style={[styles.chip, sign === item && { borderColor: colors.accent }]}
                      onPress={() => setSign(item)}
                    >
                      <Text style={[styles.chipText, sign === item && { color: colors.accent }]}>
                        {item}
                      </Text>
                    </Pressable>
                  ))
                : null}
            </View>
          </>
        ) : null}

        {selectorMode === "edges_parallel_to" ? (
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <Text style={styles.muted}>
              {ru ? "Только внешние габаритные рёбра" : "Outer bounding edges only"}
            </Text>
            <Switch
              value={outer}
              disabled={busy}
              onValueChange={setOuter}
              trackColor={{ false: colors.border, true: colors.accent2 }}
            />
          </View>
        ) : null}

        <View style={{ width: 180, gap: 4 }}>
          <Text style={styles.muted}>
            {operationMode === "fillet"
              ? ru
                ? "Радиус, мм"
                : "Radius, mm"
              : ru
                ? "Расстояние, мм"
                : "Distance, mm"}
          </Text>
          <TextInput
            style={styles.input}
            value={operationMode === "fillet" ? radius : distance}
            onChangeText={operationMode === "fillet" ? setRadius : setDistance}
            keyboardType="decimal-pad"
            selectTextOnFocus
          />
        </View>

        {activeResult.issue === "invalid_edges" ? (
          <Text style={styles.error}>
            {ru ? "Проверьте правило выбора рёбер." : "Check the edge selection rule."}
          </Text>
        ) : null}
        {dimensionIssue ? (
          <Text style={styles.error}>
            {ru
              ? `${operationMode === "fillet" ? "Радиус" : "Расстояние"} должно быть конечным числом от 0 до ${MAX_EXACT_DETAIL_MM} мм.`
              : `${operationMode === "fillet" ? "Radius" : "Distance"} must be a finite number in (0, ${MAX_EXACT_DETAIL_MM}] mm.`}
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
              if (operationMode === "fillet") {
                if (!filletResult.spec) return;
                onApplyFillet(
                  filletResult.spec,
                  `Fillet ${filletResult.spec.radius_mm} mm`,
                );
                return;
              }
              if (!chamferResult.spec) return;
              onApplyChamfer(
                chamferResult.spec,
                `Chamfer ${chamferResult.spec.distance_mm} mm`,
              );
            }}
          >
            <Text style={styles.buttonText}>
              {busy
                ? ru
                  ? "Создаём…"
                  : "Creating…"
                : operationMode === "fillet"
                  ? ru
                    ? "Создать скругление"
                    : "Create fillet"
                  : ru
                    ? "Создать фаску"
                    : "Create chamfer"}
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
