/** Mobile reachability for the existing game-ready GLB export pipeline. */
import { GAME_BUDGETS } from "@physical-ai/contracts";
import { useState } from "react";
import { Linking, Pressable, ScrollView, Switch, Text, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, radii, styles } from "./theme";

export type GameCollider = "convex" | "box" | "none";

export interface GameReadyExportOptions {
  maxTriangles: number;
  collider: GameCollider;
  lodRatios: number[];
  uv: boolean;
}

export interface GameReadyExportResult {
  downloadUrl: string;
  byteSize: number;
  report: {
    triangles_in?: number;
    lods?: { name: string; triangles: number; vertices: number; max_deviation_mm: number }[];
    collider?: { name: string; kind: "convex" | "box"; triangles: number } | null;
    uv?: boolean;
    baked_texture_px?: number | null;
  } | null;
}

export function GameReadySheet({
  visible,
  language,
  busy,
  disabledReason,
  result,
  onClose,
  onRun,
}: {
  visible: boolean;
  language: "ru" | "en";
  busy: boolean;
  disabledReason?: string | null;
  result: GameReadyExportResult | null;
  onClose: () => void;
  onRun: (options: GameReadyExportOptions) => void;
}) {
  const ru = language === "ru";
  const [budget, setBudget] = useState(20_000);
  const [collider, setCollider] = useState<GameCollider>("convex");
  const [lods, setLods] = useState(true);
  const [uv, setUv] = useState(true);
  const selectedBudget = GAME_BUDGETS.find((item) => item.triangles === budget) ?? GAME_BUDGETS[1]!;
  const disabled = busy || Boolean(disabledReason);

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="92%"
      tabletWidth={560}
      phoneBackdropColor="rgba(0,0,0,0.72)"
      accessibilityLabel={ru ? "Закрыть подготовку для игр" : "Close game-ready export"}
      contentGap={12}
    >
      <View style={{ flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.title}>{ru ? "Для игровых движков" : "For game engines"}</Text>
          <Text style={styles.sectionSubtitle}>
            {ru
              ? "Облегчённая сетка, LOD, UV, PBR и коллайдер в одном GLB."
              : "A lighter mesh, LODs, UVs, PBR and a collider in one GLB."}
          </Text>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel={ru ? "Закрыть" : "Close"} hitSlop={12} onPress={onClose}>
          <Text style={[styles.sectionTitle, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={{ gap: 14 }} showsVerticalScrollIndicator={false}>
        <View style={{ gap: 8 }}>
          <Text style={styles.heading}>{ru ? "Плотность LOD0" : "LOD0 density"}</Text>
          <View accessibilityRole="radiogroup" style={{ flexDirection: "row", gap: 7 }}>
            {GAME_BUDGETS.map((item) => {
              const active = item.triangles === budget;
              return (
                <Pressable
                  key={item.id}
                  accessibilityRole="radio"
                  accessibilityState={{ checked: active }}
                  onPress={() => setBudget(item.triangles)}
                  style={[
                    styles.chip,
                    { flex: 1, minHeight: 44, alignItems: "center", justifyContent: "center" },
                    active && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong },
                  ]}
                >
                  <Text style={[styles.chipText, active && { color: colors.accent, fontWeight: "800" }]}>
                    {item.title[language]}
                  </Text>
                </Pressable>
              );
            })}
          </View>
          <Text style={styles.muted}>
            {selectedBudget.use[language]} · {budget.toLocaleString(ru ? "ru-RU" : "en-US")} {ru ? "треугольников" : "triangles"}
          </Text>
        </View>

        <View style={{ gap: 8 }}>
          <Text style={styles.heading}>{ru ? "Топология" : "Topology"}</Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <View style={[styles.chip, { flex: 1, minHeight: 44, alignItems: "center", justifyContent: "center", borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}>
              <Text style={[styles.chipText, { color: colors.accent, fontWeight: "800" }]}>Triangle</Text>
            </View>
            <View accessibilityState={{ disabled: true }} style={[styles.chip, { flex: 1, minHeight: 44, alignItems: "center", justifyContent: "center", opacity: 0.42 }]}>
              <Text style={styles.chipText}>Quad · {ru ? "скоро" : "soon"}</Text>
            </View>
          </View>
          <Text style={styles.muted}>
            {ru
              ? "Сейчас это проверяемая треугольная decimation, а не обещание автоматической quad-retopology."
              : "This is verified triangle decimation, not a claim of automatic quad retopology."}
          </Text>
        </View>

        <View style={{ gap: 8 }}>
          <Text style={styles.heading}>{ru ? "Коллайдер" : "Collider"}</Text>
          <View accessibilityRole="radiogroup" style={{ flexDirection: "row", gap: 7 }}>
            {(["convex", "box", "none"] as const).map((kind) => {
              const active = collider === kind;
              const label = kind === "convex" ? (ru ? "Выпуклый" : "Convex") : kind === "box" ? (ru ? "Коробка" : "Box") : (ru ? "Нет" : "None");
              return (
                <Pressable
                  key={kind}
                  accessibilityRole="radio"
                  accessibilityState={{ checked: active }}
                  onPress={() => setCollider(kind)}
                  style={[styles.chip, { flex: 1, minHeight: 40, alignItems: "center", justifyContent: "center" }, active && { borderColor: colors.selection }]}
                >
                  <Text style={[styles.chipText, active && { color: colors.selection }]}>{label}</Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        <View style={{ borderRadius: radii.section, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.panel2, overflow: "hidden" }}>
          <OptionSwitch
            label={ru ? "LOD0–LOD2" : "LOD0–LOD2"}
            note={ru ? "Две облегчённые версии для дальних планов" : "Two lighter versions for distant views"}
            value={lods}
            onValueChange={setLods}
          />
          <OptionSwitch
            label={ru ? "UV-развёртка" : "UV unwrap"}
            note={ru ? "Для PBR-материала и сохранения покраски" : "For PBR materials and preserved paint"}
            value={uv}
            onValueChange={setUv}
            borderTop
          />
        </View>

        {disabledReason && <Text style={[styles.muted, { color: colors.yellow }]}>{disabledReason}</Text>}

        <Pressable
          accessibilityRole="button"
          disabled={disabled}
          onPress={() => onRun({ maxTriangles: budget, collider, lodRatios: lods ? [0.5, 0.2] : [], uv })}
          style={[styles.button, styles.buttonPrimary, { minHeight: 52 }, disabled && { opacity: 0.48 }]}
        >
          <Text style={styles.buttonText}>{busy ? (ru ? "Готовим GLB…" : "Preparing GLB…") : (ru ? "Подготовить игровой GLB" : "Prepare game-ready GLB")}</Text>
        </Pressable>

        {result && (
          <View style={{ gap: 9, padding: 13, borderRadius: radii.section, borderWidth: 1, borderColor: colors.green, backgroundColor: colors.greenWash }}>
            <Text style={[styles.heading, { color: colors.green }]}>{ru ? "Игровой файл готов" : "Game-ready file is ready"}</Text>
            <Text style={styles.muted}>
              {(result.byteSize / 1024 / 1024).toFixed(1)} MB
              {result.report?.triangles_in ? ` · ${result.report.triangles_in.toLocaleString(ru ? "ru-RU" : "en-US")} → ${result.report.lods?.[0]?.triangles?.toLocaleString(ru ? "ru-RU" : "en-US") ?? "—"} ${ru ? "треуг." : "tris"}` : ""}
            </Text>
            {result.report?.lods?.length ? (
              <Text style={styles.mono}>{result.report.lods.map((lod) => `${lod.name}: ${lod.triangles.toLocaleString()}`).join(" · ")}</Text>
            ) : null}
            <Pressable style={[styles.button, { borderColor: colors.green }]} onPress={() => void Linking.openURL(result.downloadUrl)}>
              <Text style={[styles.buttonText, { color: colors.green }]}>{ru ? "Скачать GLB" : "Download GLB"}</Text>
            </Pressable>
          </View>
        )}

        <Text style={styles.sectionSubtitle}>
          {ru
            ? "Экспорт использует метры и +Y вверх, ставит pivot в основании и именует LOD/UCX для Unity, Unreal и Godot."
            : "The export uses metres and +Y up, places the pivot at the base, and names LOD/UCX nodes for Unity, Unreal and Godot."}
        </Text>
      </ScrollView>
    </SheetShell>
  );
}

function OptionSwitch({
  label,
  note,
  value,
  onValueChange,
  borderTop = false,
}: {
  label: string;
  note: string;
  value: boolean;
  onValueChange: (value: boolean) => void;
  borderTop?: boolean;
}) {
  return (
    <View style={{ minHeight: 64, paddingHorizontal: 12, paddingVertical: 10, flexDirection: "row", alignItems: "center", gap: 12, borderTopWidth: borderTop ? 1 : 0, borderTopColor: colors.border }}>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={styles.heading}>{label}</Text>
        <Text style={styles.sectionSubtitle}>{note}</Text>
      </View>
      <Switch
        value={value}
        onValueChange={onValueChange}
        trackColor={{ false: colors.border, true: colors.accentButton }}
        thumbColor={colors.text}
      />
    </View>
  );
}
