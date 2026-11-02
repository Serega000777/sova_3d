/** Mobile reachability for the existing game-ready GLB export pipeline. */
import { GAME_BUDGETS } from "@physical-ai/contracts";
import { useEffect, useMemo, useState } from "react";
import { Linking, Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";

import { parseLodRatios, type VerifiedGameSceneObject } from "./game-ready";
import { ModelViewer, type ModelAppearance, type ViewerScenePart } from "./ModelViewer";
import { parseQuadTargetFaces, type VerifiedQuadRemesh } from "./quad-remesh";
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
    ok?: boolean;
    pivot?: string;
    file_bytes?: number;
    size_m?: number[] | null;
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
    objects?: number;
  } | null;
  /** Present only for an explicit-scene export: every visible object's own verified evidence. */
  sceneObjects?: VerifiedGameSceneObject[];
}

export interface QuadRemeshResult extends VerifiedQuadRemesh {
  downloadUrl: string;
}

export function GameReadySheet({
  visible,
  language,
  busy,
  disabledReason,
  triangleOnlyReason,
  result,
  quadResult,
  onClose,
  onRun,
  onRunQuad,
}: {
  visible: boolean;
  language: "ru" | "en";
  busy: boolean;
  /** Blocks both topologies (e.g. no active version). */
  disabledReason?: string | null;
  /** Blocks only the triangle game-ready GLB path; quad-remesh supports explicit scenes. */
  triangleOnlyReason?: string | null;
  result: GameReadyExportResult | null;
  quadResult: QuadRemeshResult | null;
  onClose: () => void;
  onRun: (options: GameReadyExportOptions) => void;
  onRunQuad: (targetFaces: number) => void;
}) {
  const ru = language === "ru";
  const [budget, setBudget] = useState(20_000);
  const [collider, setCollider] = useState<GameCollider>("convex");
  const [lods, setLods] = useState(true);
  const [lod1Percent, setLod1Percent] = useState("50");
  const [lod2Percent, setLod2Percent] = useState("20");
  const [uv, setUv] = useState(true);
  const [topology, setTopology] = useState<"triangle" | "quad">("triangle");
  const [quadTargetFaces, setQuadTargetFaces] = useState("4000");
  const [previewSceneNodeId, setPreviewSceneNodeId] = useState<string | null>(null);
  const [previewLodIndex, setPreviewLodIndex] = useState(0);
  const [previewLod, setPreviewLod] = useState<string | null>(null);
  const [previewAppearance, setPreviewAppearance] = useState<ModelAppearance>("source");
  useEffect(() => {
    const firstSceneObject = result?.sceneObjects?.[0];
    setPreviewSceneNodeId(null);
    setPreviewLodIndex(0);
    setPreviewLod(firstSceneObject ? null : result?.report?.lods?.[0]?.name ?? null);
    setPreviewAppearance("source");
  }, [result]);
  const selectedBudget = GAME_BUDGETS.find((item) => item.triangles === budget) ?? GAME_BUDGETS[1]!;
  const parsedLods = parseLodRatios(lod1Percent, lod2Percent);
  const parsedQuadTarget = parseQuadTargetFaces(quadTargetFaces);
  const lodError = lods && !parsedLods.ok
    ? parsedLods.reason === "order"
      ? (ru ? "LOD2 должен быть легче LOD1." : "LOD2 must be lighter than LOD1.")
      : (ru ? "Введите для LOD1 и LOD2 значения от 1 до 99%." : "Enter 1–99% for LOD1 and LOD2.")
    : null;
  const quadError = topology === "quad" && !parsedQuadTarget.ok
    ? (ru ? "Введите целое число граней от 100 до 100 000." : "Enter an integer face count from 100 to 100,000.")
    : null;
  const effectiveReason = disabledReason ?? (topology === "triangle" ? triangleOnlyReason : null);
  const disabled = busy
    || Boolean(effectiveReason)
    || (topology === "triangle" ? Boolean(lodError) : Boolean(quadError));
  const previewWholeScene = Boolean(result?.sceneObjects && previewSceneNodeId === null);
  const previewSceneObject = previewWholeScene
    ? null
    : result?.sceneObjects?.find((entry) => entry.node_id === previewSceneNodeId)
      ?? result?.sceneObjects?.[0]
      ?? null;
  const previewLods = previewWholeScene
    ? result?.sceneObjects?.[0]?.lods ?? []
    : previewSceneObject?.lods ?? result?.report?.lods ?? [];
  const previewColliderName = previewWholeScene
    ? null
    : previewSceneObject?.colliderName ?? result?.report?.collider?.name ?? null;
  const previewHasUv = previewWholeScene
    ? Boolean(result?.sceneObjects?.length && result.sceneObjects.every((entry) => entry.hasUv))
    : previewSceneObject?.hasUv ?? Boolean(result?.report?.uv);
  const previewIsCollider = Boolean(previewLod && previewColliderName === previewLod);
  const previewWholeSceneParts = useMemo<ViewerScenePart[] | undefined>(() => {
    if (!previewWholeScene || !result?.sceneObjects) return undefined;
    const names = result.sceneObjects.map((entry) => entry.lods[previewLodIndex]?.name ?? null);
    if (names.some((name) => name === null)) return [];
    return result.sceneObjects.map((entry, index) => ({
      id: entry.node_id,
      url: result.downloadUrl,
      format: "glb",
      glbMeshName: names[index]!,
      worldTransform: [],
    }));
  }, [previewLodIndex, previewWholeScene, result?.downloadUrl, result?.sceneObjects]);
  const previewReady = previewWholeScene
    ? previewWholeSceneParts?.length === result?.sceneObjects?.length
    : Boolean(previewLod);

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="92%"
      tabletWidth={560}
      phoneBackdropColor="rgba(0,0,0,0.72)"
      accessibilityLabel={topology === "quad"
        ? (ru ? "Закрыть quad-топологию" : "Close quad topology")
        : (ru ? "Закрыть подготовку для игр" : "Close game-ready export")}
      contentGap={12}
    >
      <View style={{ flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.title}>
            {topology === "quad"
              ? (ru ? "Quad-топология" : "Quad topology")
              : (ru ? "Для игровых движков" : "For game engines")}
          </Text>
          <Text style={styles.sectionSubtitle}>
            {topology === "quad"
              ? (ru ? "Отдельный quad-dominant FBX через sandboxed Blender." : "A separate quad-dominant FBX through sandboxed Blender.")
              : (ru ? "Облегчённая сетка, LOD, UV, PBR и коллайдер в одном GLB." : "A lighter mesh, LODs, UVs, PBR and a collider in one GLB.")}
          </Text>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel={ru ? "Закрыть" : "Close"} hitSlop={12} onPress={onClose}>
          <Text style={[styles.sectionTitle, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={{ gap: 14 }} showsVerticalScrollIndicator={false}>
        {topology === "triangle" ? (
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
        ) : null}

        <View style={{ gap: 8 }}>
          <Text style={styles.heading}>{ru ? "Топология" : "Topology"}</Text>
          <View accessibilityRole="radiogroup" style={{ flexDirection: "row", gap: 8 }}>
            {(["triangle", "quad"] as const).map((kind) => {
              const active = topology === kind;
              return (
                <Pressable
                  key={kind}
                  accessibilityRole="radio"
                  accessibilityState={{ checked: active, disabled: busy }}
                  disabled={busy}
                  onPress={() => setTopology(kind)}
                  style={[
                    styles.chip,
                    { flex: 1, minHeight: 44, alignItems: "center", justifyContent: "center" },
                    active && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong },
                    busy && { opacity: 0.55 },
                  ]}
                >
                  <Text style={[styles.chipText, active && { color: colors.accent, fontWeight: "800" }]}>
                    {kind === "triangle" ? "Triangle · GLB" : "Quad · FBX"}
                  </Text>
                </Pressable>
              );
            })}
          </View>
          <Text style={styles.muted}>
            {topology === "triangle"
              ? (ru
                  ? "Проверяемая треугольная decimation сохраняет GLB, LOD, UV и коллайдер."
                  : "Verified triangle decimation keeps the GLB, LODs, UVs and collider.")
              : (ru
                  ? "Blender QuadriFlow перестраивает каждый mesh в quad-dominant FBX, проецирует активную UV-карту и сохраняет material slots с встроенными исходными текстурами. Швы и текстуры не перестраиваются; операция может занять несколько минут."
                  : "Blender QuadriFlow rebuilds each mesh as a quad-dominant FBX, projects its active UV map and preserves material slots with embedded source textures. Seams and textures are not rebuilt, and the operation may take several minutes.")}
          </Text>
        </View>

        {topology === "quad" ? (
          <View style={{ gap: 7 }}>
            <Text style={styles.heading}>{ru ? "Целевое число граней" : "Target face count"}</Text>
            <TextInput
              accessibilityLabel={ru ? "Целевое число quad-граней" : "Target quad face count"}
              keyboardType="number-pad"
              maxLength={6}
              value={quadTargetFaces}
              onChangeText={setQuadTargetFaces}
              style={styles.input}
            />
            <Text style={styles.sectionSubtitle}>
              {ru
                ? "Допустимо 100–100 000. Это цель QuadriFlow, а не обещание точного числа или 100% quad на любой геометрии."
                : "Allowed: 100–100,000. This is a QuadriFlow target, not a promise of an exact count or 100% quads on every mesh."}
            </Text>
            {quadError ? <Text style={[styles.muted, { color: colors.red }]}>{quadError}</Text> : null}
          </View>
        ) : null}

        {topology === "triangle" ? <View style={{ gap: 8 }}>
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
        </View> : null}

        {topology === "triangle" ? <View style={{ borderRadius: radii.section, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.panel2, overflow: "hidden" }}>
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
        </View> : null}

        {topology === "triangle" && lods ? (
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

        {effectiveReason && <Text style={[styles.muted, { color: colors.yellow }]}>{effectiveReason}</Text>}

        <Pressable
          accessibilityRole="button"
          disabled={disabled}
          onPress={() => {
            if (topology === "quad") {
              if (parsedQuadTarget.ok) onRunQuad(parsedQuadTarget.value);
              return;
            }
            onRun({
              maxTriangles: budget,
              collider,
              lodRatios: lods && parsedLods.ok ? parsedLods.ratios : [],
              uv,
            });
          }}
          style={[styles.button, styles.buttonPrimary, { minHeight: 52 }, disabled && { opacity: 0.48 }]}
        >
          <Text style={styles.buttonText}>
            {busy
              ? (topology === "quad" ? (ru ? "Строим quad FBX…" : "Building quad FBX…") : (ru ? "Готовим GLB…" : "Preparing GLB…"))
              : (topology === "quad" ? (ru ? "Построить quad FBX" : "Build quad FBX") : (ru ? "Подготовить игровой GLB" : "Prepare game-ready GLB"))}
          </Text>
        </Pressable>

        {topology === "quad" && quadResult ? (
          <View
            accessibilityLabel={ru ? "Проверенный результат QuadriFlow" : "Verified QuadriFlow result"}
            style={{ gap: 9, padding: 13, borderRadius: radii.section, borderWidth: 1, borderColor: colors.green, backgroundColor: colors.greenWash }}
          >
            <Text style={[styles.heading, { color: colors.green }]}>{ru ? "Quad FBX готов" : "Quad FBX is ready"}</Text>
            <Text style={styles.muted}>
              {(quadResult.byteSize / 1024 / 1024).toFixed(1)} MB
              {` · ${quadResult.report.faces.toLocaleString(ru ? "ru-RU" : "en-US")} ${ru ? "граней" : "faces"}`}
            </Text>
            <Text style={styles.mono}>
              {ru ? "Quad-доля" : "Quad ratio"} · {(quadResult.report.quadRatio * 100).toLocaleString(ru ? "ru-RU" : "en-US", { maximumFractionDigits: 2 })}%
              {` · ${quadResult.report.quadFaces.toLocaleString(ru ? "ru-RU" : "en-US")} quad`}
            </Text>
            <Text style={styles.sectionSubtitle}>
              {`${quadResult.report.triangleFaces.toLocaleString(ru ? "ru-RU" : "en-US")} tri · ${quadResult.report.otherFaces.toLocaleString(ru ? "ru-RU" : "en-US")} ${ru ? "прочих" : "other"} · ${quadResult.report.vertices.toLocaleString(ru ? "ru-RU" : "en-US")} ${ru ? "вершин" : "vertices"}`}
            </Text>
            <Text style={styles.sectionSubtitle}>
              Blender {quadResult.report.blenderVersion} · {ru ? "цель" : "target"} {quadResult.targetFaces.toLocaleString(ru ? "ru-RU" : "en-US")}
            </Text>
            <Text style={styles.sectionSubtitle}>
              {quadResult.report.uvTransfer === "active_surface_projected"
                ? (ru
                    ? `UV · активная карта спроецирована на новую поверхность (${quadResult.report.uvCoordinates?.toLocaleString("ru-RU") ?? "—"} координат)`
                    : `UV · the active map was surface-projected onto the new mesh (${quadResult.report.uvCoordinates?.toLocaleString("en-US") ?? "—"} coordinates)`)
                : quadResult.report.uvTransfer === "none"
                  ? (ru ? "UV · у исходной модели не было UV-карты" : "UV · the source model had no UV map")
                  : quadResult.objects.length > 1
                    ? (ru ? "UV · разная у каждого объекта, см. список ниже" : "UV · differs per object, see the list below")
                    : (ru ? "UV · старый отчёт не содержит доказательства переноса" : "UV · the legacy report has no transfer evidence")}
            </Text>
            <Text style={styles.sectionSubtitle}>
              {quadResult.report.materials === null
                ? (ru ? "Материалы · старый отчёт без доказательства упаковки" : "Materials · legacy report without packaging evidence")
                : (ru
                    ? `Материалы · ${quadResult.report.materials.length} слотов, ${quadResult.report.materials.reduce((total, material) => total + material.textureSha256s.length, 0)} встроенных текстур`
                    : `Materials · ${quadResult.report.materials.length} slots, ${quadResult.report.materials.reduce((total, material) => total + material.textureSha256s.length, 0)} embedded textures`)}
            </Text>
            {quadResult.objects.length > 1 && (
              <View style={{ gap: 5 }}>
                <Text style={styles.sectionSubtitle}>
                  {ru ? `${quadResult.objects.length} объекта сцены:` : `${quadResult.objects.length} scene objects:`}
                </Text>
                {quadResult.objects.map((entry) => (
                  <Text key={entry.name ?? ""} style={styles.mono}>
                    {entry.name} · {entry.faces.toLocaleString(ru ? "ru-RU" : "en-US")} {ru ? "граней" : "faces"} ·{" "}
                    {(entry.quadRatio * 100).toFixed(1)}% quad ·{" "}
                    {entry.uvTransfer === "active_surface_projected"
                      ? (ru ? "UV перенесён" : "UV transferred")
                      : (ru ? "без UV" : "no UV")}
                    {entry.materials === null
                      ? ""
                      : ` · ${entry.materials.length} ${ru ? "мат." : "mat."} · ${entry.materials.reduce((total, material) => total + material.textureSha256s.length, 0)} ${ru ? "текстур" : "textures"}`}
                  </Text>
                ))}
              </View>
            )}
            <Pressable style={[styles.button, { borderColor: colors.green }]} onPress={() => void Linking.openURL(quadResult.downloadUrl)}>
              <Text style={[styles.buttonText, { color: colors.green }]}>{ru ? "Открыть / скачать FBX" : "Open / download FBX"}</Text>
            </Pressable>
          </View>
        ) : null}

        {topology === "triangle" && result && (
          <View style={{ gap: 9, padding: 13, borderRadius: radii.section, borderWidth: 1, borderColor: colors.green, backgroundColor: colors.greenWash }}>
            <Text style={[styles.heading, { color: colors.green }]}>{ru ? "Игровой файл готов" : "Game-ready file is ready"}</Text>
            <Text style={styles.muted}>
              {(result.byteSize / 1024 / 1024).toFixed(1)} MB
              {result.sceneObjects
                ? ` · ${ru ? "объектов" : "objects"}: ${result.sceneObjects.length} · ${result.report?.triangles_in?.toLocaleString(ru ? "ru-RU" : "en-US") ?? "—"} ${ru ? "исходных треуг." : "input tris"}`
                : result.report?.triangles_in
                  ? ` · ${result.report.triangles_in.toLocaleString(ru ? "ru-RU" : "en-US")} → ${result.report.lods?.[0]?.triangles?.toLocaleString(ru ? "ru-RU" : "en-US") ?? "—"} ${ru ? "треуг." : "tris"}`
                  : ""}
            </Text>
            {result.report?.size_m?.length === 3 ? (
              <Text style={styles.mono}>
                {ru ? "Размер в движке X × Y(вверх) × Z" : "Engine size X × Y(up) × Z"}: {result.report.size_m.map((value) => value.toLocaleString(ru ? "ru-RU" : "en-US", { maximumFractionDigits: 6 })).join(" × ")} {ru ? "м" : "m"} · pivot: {result.report.pivot}
              </Text>
            ) : null}
            {result.sceneObjects ? (
              <View style={{ gap: 5 }}>
                <Text style={styles.sectionSubtitle}>
                  {ru
                    ? `Объектов сцены: ${result.sceneObjects.length}; у каждого свой LOD/коллайдер:`
                    : `${result.sceneObjects.length} scene objects, each with its own LOD/collider:`}
                </Text>
                <ScrollView
                  horizontal
                  showsHorizontalScrollIndicator={false}
                  contentContainerStyle={{ gap: 6 }}
                  accessibilityRole="radiogroup"
                >
                  <Pressable
                    accessibilityRole="radio"
                    accessibilityState={{ checked: previewWholeScene }}
                    onPress={() => {
                      setPreviewSceneNodeId(null);
                      setPreviewLodIndex(0);
                      setPreviewLod(null);
                      setPreviewAppearance("source");
                    }}
                    style={[styles.chip, previewWholeScene && { borderColor: colors.selection }]}
                  >
                    <Text style={[styles.chipText, previewWholeScene && { color: colors.selection }]}>
                      {ru ? "Вся сцена" : "Whole scene"}
                    </Text>
                  </Pressable>
                  {result.sceneObjects.map((entry) => {
                    const selected = entry.node_id === previewSceneObject?.node_id;
                    return (
                      <Pressable
                        key={`preview-${entry.node_id}`}
                        accessibilityRole="radio"
                        accessibilityState={{ checked: selected }}
                        onPress={() => {
                          setPreviewSceneNodeId(entry.node_id);
                          setPreviewLodIndex(0);
                          setPreviewLod(entry.lods[0]?.name ?? null);
                          setPreviewAppearance("source");
                        }}
                        style={[styles.chip, selected && { borderColor: colors.selection }]}
                      >
                        <Text style={[styles.chipText, selected && { color: colors.selection }]}>
                          {entry.name}
                        </Text>
                      </Pressable>
                    );
                  })}
                </ScrollView>
                {result.sceneObjects.map((entry) => (
                  <Text key={entry.node_id} style={styles.mono}>
                    {entry.name} · {entry.triangles_in.toLocaleString(ru ? "ru-RU" : "en-US")} →{" "}
                    {entry.lod0Triangles.toLocaleString(ru ? "ru-RU" : "en-US")} {ru ? "треуг." : "tris"}
                    {entry.colliderTriangles !== null
                      ? ` · ${ru ? "коллайдер" : "collider"} ${entry.colliderTriangles.toLocaleString(ru ? "ru-RU" : "en-US")}`
                      : ` · ${ru ? "без коллайдера" : "no collider"}`}
                    {entry.animated ? ` · ${ru ? "rigid-анимация" : "rigid animation"}` : ""}
                    {entry.material
                      ? ` · ${entry.material.catalogMaterialId}${entry.material.sourceTextureSha256 ? ` · ${ru ? "texture LOD" : "texture LOD"} ${entry.material.embeddedTexturePx.join("/")}` : ""}`
                      : ""}
                    {entry.engineName !== entry.name ? ` · GLB: ${entry.engineName}` : ""}
                  </Text>
                ))}
                <Text style={styles.sectionSubtitle}>
                  {ru
                    ? "Относительное положение объектов сохранено. Выберите всю сцену для общего LOD/UV или отдельный объект для его точного LOD/UV/UCX."
                    : "Relative object placement is preserved. Select the whole scene for a shared LOD/UV view or one object for its exact LOD/UV/UCX."}
                </Text>
                <Text style={styles.sectionSubtitle}>
                  {result.sceneObjects.some((entry) => entry.animated)
                    ? (ru
                        ? "Доверенная rigid-анимация механизма перенесена вместе со всеми LOD и UCX движущегося узла."
                        : "The trusted rigid mechanism animation is carried with every LOD and UCX child of the moving node.")
                    : (ru
                        ? "У этой сцены нет одной доверенной rigid-анимации."
                        : "This scene has no single trusted rigid animation.")}
                </Text>
                <Text style={styles.sectionSubtitle}>
                  {result.sceneObjects.some((entry) => entry.material)
                    ? (ru
                        ? "Доверенные материалы каталога перенесены по объектам; текстурные покрытия запечены в отдельный нормализованный atlas каждого LOD."
                        : "Trusted catalogue materials are carried per object; textured finishes are baked into each LOD's own normalized atlas.")
                    : (ru
                        ? "У объектов этой сцены нет назначенных материалов каталога."
                        : "This scene has no assigned catalogue materials.")}
                </Text>
              </View>
            ) : null}
            {!result.sceneObjects && result.report?.lods?.length ? (
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
            {previewLods.length && previewReady ? (
              <View style={{ gap: 8 }} accessibilityLabel={ru ? "Предпросмотр уровней детализации" : "Level of detail preview"}>
                <View style={styles.row} accessibilityRole="radiogroup">
                  {previewLods.map((lod, index) => (
                    <Pressable
                      key={lod.name}
                      accessibilityRole="radio"
                      accessibilityState={{
                        checked: previewWholeScene ? previewLodIndex === index : previewLod === lod.name,
                      }}
                      onPress={() => {
                        setPreviewLodIndex(index);
                        setPreviewLod(previewWholeScene ? null : lod.name);
                        setPreviewAppearance("source");
                      }}
                      style={[
                        styles.chip,
                        (previewWholeScene ? previewLodIndex === index : previewLod === lod.name)
                          && { borderColor: colors.accent },
                      ]}
                    >
                      <Text
                        style={[
                          styles.chipText,
                          (previewWholeScene ? previewLodIndex === index : previewLod === lod.name)
                            && { color: colors.accent },
                        ]}
                      >
                        LOD{index}
                      </Text>
                    </Pressable>
                  ))}
                  {previewColliderName ? (
                    <Pressable
                      accessibilityRole="radio"
                      accessibilityState={{ checked: previewIsCollider }}
                      onPress={() => {
                        setPreviewLod(previewColliderName);
                        setPreviewAppearance("mesh");
                      }}
                      style={[styles.chip, previewIsCollider && { borderColor: colors.yellow }]}
                    >
                      <Text style={[styles.chipText, previewIsCollider && { color: colors.yellow }]}>Collider</Text>
                    </Pressable>
                  ) : null}
                </View>
                {previewHasUv && !previewIsCollider ? (
                  <View style={styles.row} accessibilityRole="radiogroup">
                    {([
                      { value: "source", ru: "Материал", en: "Material" },
                      { value: "uv_checker", ru: "UV-сетка", en: "UV checker" },
                    ] as const).map((option) => (
                      <Pressable
                        key={option.value}
                        accessibilityRole="radio"
                        accessibilityState={{ checked: previewAppearance === option.value }}
                        onPress={() => setPreviewAppearance(option.value)}
                        style={[styles.chip, previewAppearance === option.value && { borderColor: colors.selection }]}
                      >
                        <Text style={[styles.chipText, previewAppearance === option.value && { color: colors.selection }]}>
                          {ru ? option.ru : option.en}
                        </Text>
                      </Pressable>
                    ))}
                  </View>
                ) : null}
                <ModelViewer
                  url={previewWholeScene ? null : result.downloadUrl}
                  sceneParts={previewWholeScene ? previewWholeSceneParts : undefined}
                  format="glb"
                  glbMeshName={previewWholeScene ? null : previewLod}
                  appearance={previewAppearance}
                  bodyId={previewWholeScene
                    ? `game-ready-scene-lod-${previewLodIndex}`
                    : `game-ready-${previewSceneObject?.node_id ?? "single"}-${previewLod}`}
                  selected={false}
                  onSelect={() => undefined}
                  height={240}
                  showGrid={false}
                />
                <Text style={styles.sectionSubtitle}>
                  {previewWholeScene
                    ? (ru
                        ? `Показан LOD${previewLodIndex} каждого проверенного объекта с сохранённым взаимным положением. Это ручное сравнение всей сборки, не автоматическое переключение по расстоянию движка.`
                        : `LOD${previewLodIndex} is shown for every verified object with relative placement preserved. This is a manual whole-assembly comparison, not an engine's automatic distance switch.`)
                    : previewIsCollider
                    ? (ru
                        ? "Показан ровно именованный UCX-коллайдер из экспортного GLB. Это просмотр одной collision-формы, а не симуляция столкновений, массы или динамики."
                        : "This is the exact named UCX collider from the exported GLB. It previews one collision shape; it does not simulate contacts, mass or dynamics.")
                    : previewAppearance === "uv_checker"
                    ? (ru
                        ? "UV-сетка рисуется по координатам выбранного узла из готового GLB. Она помогает увидеть швы и растяжение, но не является оценкой упаковки или редактором развёртки."
                        : "The checker uses the selected node's UV coordinates from the exported GLB. It helps inspect seams and stretching, but is not a packing score or unwrap editor.")
                    : (ru
                        ? "Просмотр загружает ровно выбранный узел из готового GLB; это ручное сравнение, не автоматический выбор по расстоянию."
                        : "The preview loads exactly the selected node from the exported GLB; this is manual comparison, not automatic distance switching.")}
                </Text>
              </View>
            ) : null}
            {!result.sceneObjects && result.report ? (
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
                {result.report.uv ? result.report.uv_atlases?.map((atlas, index) => (
                  <Text key={atlas.lod} style={styles.sectionSubtitle}>
                    UV LOD{index} · {ru ? "площадь треугольников" : "triangle area"} {atlas.triangle_area_pct.toLocaleString(ru ? "ru-RU" : "en-US", { maximumFractionDigits: 2 })}%
                    {` · ${ru ? "вне атласа" : "out of bounds"} ${atlas.out_of_bounds_vertices}`}
                    {` · ${ru ? "вырожденных" : "degenerate"} ${atlas.degenerate_triangles}`}
                  </Text>
                )) : null}
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

        {topology === "triangle" ? (
          <>
            <Text style={styles.sectionSubtitle}>
              {ru
                ? "Экспорт использует метры и +Y вверх, ставит pivot в основании и именует LOD/UCX для Unity, Unreal и Godot."
                : "The export uses metres and +Y up, places the pivot at the base, and names LOD/UCX nodes for Unity, Unreal and Godot."}
            </Text>
            <Text style={styles.sectionSubtitle}>
              {ru
                ? "Отчёт проверяет каждый экспортный коллайдер. Столкновения между объектами сцены, массу, гравитацию и динамику он не моделирует."
                : "The report verifies every exported collider. It does not simulate scene-object collisions, mass, gravity or dynamics."}
            </Text>
          </>
        ) : (
          <Text style={styles.sectionSubtitle}>
            {ru
              ? "FBX содержит перестроенную топологию одного объекта. Исходный GLB и immutable-версия не изменяются."
              : "The FBX contains rebuilt topology for one object. The source GLB and immutable version are unchanged."}
          </Text>
        )}
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
