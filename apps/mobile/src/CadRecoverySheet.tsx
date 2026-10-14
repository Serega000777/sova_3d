import type {
  AnyCadProfileSeed,
  CadProfileFailureCode,
  CadProfileResult,
} from "@physical-ai/contracts";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

type Language = "ru" | "en";

function failure(code: CadProfileFailureCode, ru: boolean): string {
  const labels: Record<CadProfileFailureCode, [string, string]> = {
    selection_empty: ["Select faces first.", "Сначала выберите грани."],
    selection_too_large: [
      "The patch is too large to convert safely.",
      "Область слишком большая для безопасного преобразования.",
    ],
    face_missing: [
      "The selection is stale. Select the faces again.",
      "Выбор устарел. Выберите грани заново.",
    ],
    selection_disconnected: [
      "Select one connected face patch.",
      "Выберите одну связную область граней.",
    ],
    selection_non_planar: [
      "The selected faces are neither planar nor one supported analytic surface.",
      "Выбранные грани не образуют ни плоскость, ни одну поддерживаемую аналитическую поверхность.",
    ],
    fit_axis_underdetermined: [
      "The curved patch has no stable analytic axis.",
      "У криволинейной области нет устойчивой аналитической оси.",
    ],
    fit_not_single_analytic_surface: [
      "The patch is not one exact cylinder, cone, or sphere.",
      "Область не является одним точным цилиндром, конусом или сферой.",
    ],
    boundary_not_axis_aligned: [
      "The trim must follow the surface axis and circles.",
      "Граница должна идти вдоль оси и окружностей поверхности.",
    ],
    boundary_crosses_seam_twice: [
      "The trim crosses the periodic seam more than once.",
      "Граница пересекает периодический шов больше одного раза.",
    ],
    boundary_too_complex: [
      "Simplify the curved boundary to at most 128 points.",
      "Упростите криволинейную границу максимум до 128 точек.",
    ],
    selection_non_manifold: [
      "The selected patch has a non-manifold edge.",
      "В выбранной области есть неманифолдное ребро.",
    ],
    selection_has_holes: [
      "A profile with holes is not supported yet.",
      "Профиль с отверстиями пока не поддерживается.",
    ],
    selection_open_boundary: [
      "The selected patch has no single closed boundary.",
      "У выбранной области нет одной замкнутой границы.",
    ],
    profile_too_small: [
      "The boundary is too small to form a profile.",
      "Граница слишком мала для профиля.",
    ],
    profile_too_complex: [
      "Simplify the boundary to at most 128 corners.",
      "Упростите границу максимум до 128 углов.",
    ],
  };
  return labels[code][ru ? 1 : 0];
}

export function CadRecoverySheet({
  visible,
  language,
  cadProfile,
  blockedReason,
  busy,
  error,
  onClose,
  onApply,
}: {
  visible: boolean;
  language: Language;
  cadProfile: CadProfileResult | null;
  blockedReason: string | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onApply: (seed: AnyCadProfileSeed, amountMm: number) => void;
}) {
  const ru = language === "ru";
  const seed = cadProfile?.ok ? cadProfile.seed : null;
  const analytic = seed !== null && "kind" in seed;
  const [extrusionHeight, setExtrusionHeight] = useState("10");
  const [surfaceThickness, setSurfaceThickness] = useState("2");

  useEffect(() => {
    if (visible && seed && "kind" in seed) setSurfaceThickness(String(seed.thickness_mm));
  }, [seed, visible]);

  const amount = Number((analytic ? surfaceThickness : extrusionHeight).replace(",", "."));
  const valid = Number.isFinite(amount) && amount > 0;

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="78%"
      tabletWidth={520}
      accessibilityLabel={ru ? "Закрыть восстановление CAD" : "Close CAD recovery"}
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.heading}>{ru ? "Mesh → точный CAD" : "Mesh → exact CAD"}</Text>
        <Pressable onPress={onClose} hitSlop={12}>
          <Text style={[styles.title, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={{ gap: 12 }} keyboardShouldPersistTaps="handled">
        <Text style={styles.muted}>
          {ru
            ? "Одна связная область граней восстанавливается только при доказанной плоскости, цилиндре, конусе или сфере. Исходный mesh останется в истории."
            : "One connected face patch is recovered only when it proves planar, cylindrical, conical, or spherical. The source mesh stays in history."}
        </Text>

        {blockedReason ? <Text style={styles.error}>{blockedReason}</Text> : null}
        {!blockedReason && cadProfile && !cadProfile.ok ? (
          <Text style={styles.error}>{failure(cadProfile.code, ru)}</Text>
        ) : null}
        {!blockedReason && !cadProfile ? (
          <Text style={styles.error}>
            {ru ? "Выберите одну или несколько граней." : "Select one or more faces."}
          </Text>
        ) : null}

        {!blockedReason && seed ? (
          <View style={{ gap: 10 }}>
            <Text style={[styles.mono, { color: colors.selection }]}>
              {analytic
                ? ru
                  ? `Точная поверхность · ${seed.surface.kind} · ${seed.source_faces} граней`
                  : `Exact surface · ${seed.surface.kind} · ${seed.source_faces} faces`
                : ru
                  ? `Точный line-sketch · ${seed.profile.points_mm.length} углов · ${seed.source_faces} граней`
                  : `Exact line sketch · ${seed.profile.points_mm.length} corners · ${seed.source_faces} faces`}
            </Text>
            <View style={[styles.row, { alignItems: "stretch" }]}>
              <View style={{ flex: 1, gap: 3, borderLeftWidth: 2, borderLeftColor: colors.selection, paddingLeft: 9 }}>
                <Text style={styles.muted}>{ru ? "Площадь" : "Area"}</Text>
                <Text style={styles.mono}>{seed.selected_area_mm2.toFixed(2)} {ru ? "мм²" : "mm²"}</Text>
              </View>
              <View style={{ flex: 1, gap: 3, borderLeftWidth: 2, borderLeftColor: colors.selection, paddingLeft: 9 }}>
                <Text style={styles.muted}>{ru ? "Среднее отклонение" : "Mean deviation"}</Text>
                <Text style={styles.mono}>{seed.mean_deviation_mm.toFixed(4)} {ru ? "мм" : "mm"}</Text>
              </View>
            </View>
            {analytic ? (
              <Text style={styles.muted}>
                {ru ? "Радиус" : "Radius"} {seed.surface.radius_mm.toFixed(3)} {ru ? "мм" : "mm"}
                {seed.surface.kind === "cone"
                  ? ` · ${ru ? "полуугол" : "half-angle"} ${seed.surface.half_angle_deg.toFixed(3)}°`
                  : ""}
              </Text>
            ) : (
              <Text style={styles.muted}>
                {ru
                  ? "Профиль будет вытянут точно по измеренной нормали выбранной плоскости."
                  : "The profile will be extruded exactly along the measured plane normal."}
              </Text>
            )}
            <Text style={styles.muted}>
              {analytic
                ? ru
                  ? "Толщина, мм"
                  : "Thickness, mm"
                : ru
                  ? "Высота выдавливания, мм"
                  : "Extrusion height, mm"}
            </Text>
            <TextInput
              style={styles.input}
              value={analytic ? surfaceThickness : extrusionHeight}
              onChangeText={analytic ? setSurfaceThickness : setExtrusionHeight}
              keyboardType="decimal-pad"
              selectTextOnFocus
            />
            {!valid ? (
              <Text style={styles.error}>
                {ru ? "Введите конечный положительный размер." : "Enter a finite positive dimension."}
              </Text>
            ) : null}
          </View>
        ) : null}

        {error ? <Text style={styles.error}>{error}</Text> : null}
        <View style={styles.row}>
          <Pressable
            style={[
              styles.button,
              styles.buttonPrimary,
              (!seed || Boolean(blockedReason) || !valid || busy) && { opacity: 0.45 },
            ]}
            disabled={!seed || Boolean(blockedReason) || !valid || busy}
            onPress={() => seed && onApply(seed, amount)}
          >
            <Text style={styles.buttonText}>
              {busy
                ? ru
                  ? "Строим…"
                  : "Building…"
                : ru
                  ? "Создать точную CAD-версию"
                  : "Create exact CAD version"}
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
