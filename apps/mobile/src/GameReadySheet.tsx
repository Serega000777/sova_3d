/** Mobile reachability for the existing game-ready GLB export pipeline. */
import { GAME_BUDGETS } from "@physical-ai/contracts";
import { useEffect, useState } from "react";
import { Linking, Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";

import { parseLodRatios } from "./game-ready";
import { ModelViewer } from "./ModelViewer";
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
    collider?: {
      name: string;
      kind: "convex" | "box";
      triangles: number;
      triangle_limit?: number;
      is_convex?: boolean;
      is_watertight?: boolean;
      volume_ratio_pct?: number | null;
      floor_offset_mm?: number;
    } | null;
    uv?: boolean;
    uv_atlases?: {
      lod: string;
      triangle_area_pct: number;
      degenerate_triangles: number;
      out_of_bounds_vertices: number;
    }[];
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
  const [lod1Percent, setLod1Percent] = useState("50");
  const [lod2Percent, setLod2Percent] = useState("20");
  const [uv, setUv] = useState(true);
  const [previewLod, setPreviewLod] = useState<string | null>(null);
  useEffect(() => {
    setPreviewLod(result?.report?.lods?.[0]?.name ?? null);
  }, [result]);
  const selectedBudget = GAME_BUDGETS.find((item) => item.triangles === budget) ?? GAME_BUDGETS[1]!;
  const parsedLods = parseLodRatios(lod1Percent, lod2Percent);
  const lodError = lods && !parsedLods.ok
    ? parsedLods.reason === "order"
      ? (ru ? "LOD2 должен быть легче LOD1." : "LOD2 must be lighter than LOD1.")
      : (ru ? "Введите для LOD1 и LOD2 значения от 1 до 99%." : "Enter 1–99% for LOD1 and LOD2.")
    : null;
  const disabled = busy || Boolean(disabledReason) || Boolean(lodError);

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

        {lods ? (
          <View style={{ gap: 8 }} accessibilityLabel={ru ? "Плотность уровней детализации" : "Level of detail density"}>
            <Text style={styles.heading}>{ru ? "Детализация дальних планов" : "Distance detail"}</Text>
            <Text style={styles.muted}>
              {ru
                ? "Каждый уровень задаётся как доля треугольников LOD0. LOD2 должен быть легче LOD1."
                : "Each level is a share of LOD0 triangles. LOD2 must be lighter than LOD1."}
            </Text>
            <View style={{ flexDirection: "row", gap: 8 }}>
              {([
                { label: "LOD1", value: lod1Percent, setValue: setLod1Percent },
                { label: "LOD2", value: lod2Percent, setValue: setLod2Percent },
              ] as const).map((field) => (
                <View key={field.label} style={{ flex: 1, gap: 5 }}>
                  <Text style={styles.sectionSubtitle}>{field.label} · % от LOD0</Text>
                  <TextInput
                    accessibilityLabel={`${field.label}, процентов от LOD0`}
                    keyboardType="decimal-pad"
                    maxLength={5}
                    value={field.value}
                    onChangeText={field.setValue}
                    style={styles.input}
                  />
                </View>
              ))}
            </View>
            {lodError ? <Text style={[styles.muted, { color: colors.red }]}>{lodError}</Text> : null}
          </View>
        ) : null}

        {disabledReason && <Text style={[styles.muted, { color: colors.yellow }]}>{disabledReason}</Text>}

        <Pressable
          accessibilityRole="button"
          disabled={disabled}
          onPress={() => onRun({
            maxTriangles: budget,
            collider,
            lodRatios: lods && parsedLods.ok ? parsedLods.ratios : [],
            uv,
          })}
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
              <View
                accessibilityLabel={ru ? "Проверенные уровни детализации" : "Verified levels of detail"}
                style={{ gap: 6 }}
              >
                {result.report.lods.map((lod, index) => (
                  <View key={lod.name} style={[styles.row, { justifyContent: "space-between" }]}>
                    <Text style={styles.mono}>LOD{index}</Text>
                    <Text style={styles.muted}>
                      {lod.triangles.toLocaleString(ru ? "ru-RU" : "en-US")} {ru ? "треуг." : "tris"}
                      {index > 0
                        ? ` · ${ru ? "отклонение ≤" : "deviation ≤"} ${lod.max_deviation_mm.toLocaleString(ru ? "ru-RU" : "en-US", { maximumFractionDigits: 3 })} ${ru ? "мм" : "mm"}`
                        : ` · ${ru ? "базовый уровень" : "base level"}`}
                    </Text>
                  </View>
                ))}
              </View>
            ) : null}
            {result.report?.lods?.length && previewLod ? (
              <View style={{ gap: 8 }} accessibilityLabel={ru ? "Предпросмотр уровней детализации" : "Level of detail preview"}>
                <View style={styles.row} accessibilityRole="radiogroup">
                  {result.report.lods.map((lod, index) => (
                    <Pressable
                      key={lod.name}
                      accessibilityRole="radio"
                      accessibilityState={{ checked: previewLod === lod.name }}
                      onPress={() => setPreviewLod(lod.name)}
                      style={[styles.chip, previewLod === lod.name && { borderColor: colors.accent }]}
                    >
                      <Text style={[styles.chipText, previewLod === lod.name && { color: colors.accent }]}>LOD{index}</Text>
                    </Pressable>
                  ))}
                </View>
                <ModelViewer
                  url={result.downloadUrl}
                  format="glb"
                  glbMeshName={previewLod}
                  bodyId={`game-ready-${previewLod}`}
                  selected={false}
                  onSelect={() => undefined}
                  height={240}
                  showGrid={false}
                />
                <Text style={styles.sectionSubtitle}>
                  {ru
                    ? "Просмотр загружает ровно выбранный узел из готового GLB; это ручное сравнение, не автоматический выбор по расстоянию."
                    : "The preview loads exactly the selected node from the exported GLB; this is manual comparison, not automatic distance switching."}
                </Text>
              </View>
            ) : null}
            {result.report ? (
              <View
                accessibilityLabel={ru ? "Проверенный состав игрового GLB" : "Verified game-ready GLB contents"}
                style={{ gap: 5, padding: 10, borderRadius: radii.control, backgroundColor: colors.panel }}
              >
                <Text style={styles.sectionSubtitle}>
                  LOD · {result.report.lods?.length
                    ? `${result.report.lods.length} ${ru ? "уровня" : "levels"}`
                    : (ru ? "только LOD0" : "LOD0 only")}
                </Text>
                <Text style={styles.sectionSubtitle}>
                  UV · {result.report.uv ? (ru ? "есть" : "included") : (ru ? "не добавлена" : "not included")}
                  {result.report.baked_texture_px
                    ? ` · ${ru ? "текстура покраски" : "paint texture"} ${result.report.baked_texture_px}px`
                    : ` · ${ru ? "исходной покраски для запекания нет" : "no source paint to bake"}`}
                </Text>
                {result.report.uv_atlases?.map((atlas, index) => (
                  <Text key={atlas.lod} style={styles.sectionSubtitle}>
                    UV LOD{index} · {ru ? "площадь треугольников" : "triangle area"} {atlas.triangle_area_pct.toLocaleString(ru ? "ru-RU" : "en-US", { maximumFractionDigits: 2 })}%
                    {` · ${ru ? "вне атласа" : "out of bounds"} ${atlas.out_of_bounds_vertices}`}
                    {` · ${ru ? "вырожденных" : "degenerate"} ${atlas.degenerate_triangles}`}
                  </Text>
                ))}
                <Text style={styles.sectionSubtitle}>
                  {ru ? "Коллайдер" : "Collider"} · {result.report.collider
                    ? `${result.report.collider.kind} · ${result.report.collider.triangles.toLocaleString(ru ? "ru-RU" : "en-US")}${result.report.collider.triangle_limit ? `/${result.report.collider.triangle_limit.toLocaleString(ru ? "ru-RU" : "en-US")}` : ""} ${ru ? "треуг." : "tris"}`
                    : (ru ? "не включён" : "not included")}
                </Text>
                {result.report.collider ? (
                  <>
                    <Text style={styles.sectionSubtitle}>
                      {ru ? "Форма" : "Shape"} · {result.report.collider.is_convex === true ? (ru ? "выпуклая" : "convex") : (ru ? "выпуклость не подтверждена" : "convexity not verified")}
                      {` · ${result.report.collider.is_watertight === true ? (ru ? "замкнутая" : "watertight") : (ru ? "замкнутость не подтверждена" : "watertightness not verified")}`}
                    </Text>
                    {result.report.collider.volume_ratio_pct !== null && result.report.collider.volume_ratio_pct !== undefined ? (
                      <Text style={styles.sectionSubtitle}>
                        {ru ? "Объём к LOD0" : "Volume vs LOD0"} · {result.report.collider.volume_ratio_pct.toLocaleString(ru ? "ru-RU" : "en-US", { maximumFractionDigits: 2 })}%
                      </Text>
                    ) : null}
                    {result.report.collider.floor_offset_mm !== undefined ? (
                      <Text style={styles.sectionSubtitle}>
                        {ru ? "Низ относительно пола" : "Bottom vs ground"} · {result.report.collider.floor_offset_mm.toLocaleString(ru ? "ru-RU" : "en-US", { maximumFractionDigits: 3 })} {ru ? "мм" : "mm"}
                      </Text>
                    ) : null}
                  </>
                ) : null}
              </View>
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
        <Text style={styles.sectionSubtitle}>
          {ru
            ? "Отчёт проверяет один экспортный коллайдер. Столкновения между объектами сцены, массу, гравитацию и динамику он не моделирует."
            : "The report verifies one exported collider. It does not simulate scene-object collisions, mass, gravity or dynamics."}
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
