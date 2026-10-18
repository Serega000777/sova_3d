/**
 * Scan result review (T-084, F-002): look at what came back, then keep it or try again.
 * Nothing enters a project until the user says so, and the scale is shown for what it is —
 * a claim with a source and a confidence (T-082).
 */
import type { Job, Project, Scan, ScanFrame } from "@physical-ai/contracts";
import { scanFrameWarnings } from "@physical-ai/contracts";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { ModelViewer } from "@/src/ModelViewer";
import { useSession } from "@/src/session";
import { colors, elevationHigh, elevationLow, radii, styles } from "@/src/theme";

interface Report {
  provider?: string;
  coverage?: number;
  note?: string;
  placeholder?: boolean;
  scale?: { applied_mm: number; source: string; confidence: number; warning: string | null };
  capture?: { frames?: number; blurry_frames?: number; mean_sharpness?: number | null };
  repair?: Record<string, unknown>;
  mask?: { mask_applied?: boolean; model?: string; frames_masked?: number };
  texture?: { texture_baked?: boolean; registered_texture_cameras?: number; reason?: string };
  multi_view?: {
    registered_images?: number;
    registered_fraction?: number;
    sparse_points?: number;
    mean_reprojection_error_px?: number | null;
    registered_by_section?: Record<string, number>;
    section_provenance?: Record<
      string,
      { captured_sequence_nos?: number[]; registered_sequence_nos?: number[] }
    >;
    section_alignment_error_deg?: Record<string, number>;
    isolated_components_removed?: number;
    metric_scale_factor?: number;
    scale_confidence?: number;
  };
}

type PreviewMode = "texture" | "mesh" | "empty";

interface RoomPlanStats {
  floor_plan?: { walls?: unknown[]; openings?: unknown[] };
  room_shell?: {
    outline_mm?: number[][];
    wall_height_mm?: number;
    openings?: unknown[];
  };
}

function polygonAreaM2(outline: number[][] | undefined): number | null {
  if (!outline || outline.length < 3) return null;
  const areaMm2 = outline.reduce((sum, point, index) => {
    const next = outline[(index + 1) % outline.length];
    return next ? sum + point[0] * next[1] - next[0] * point[1] : sum;
  }, 0);
  return Math.abs(areaMm2) / 2_000_000;
}

const EXTERIOR_SECTIONS = ["front", "right", "back", "left", "roof"] as const;

export default function ScanResult() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { session, client } = useSession();

  const [scan, setScan] = useState<Scan | null>(null);
  const [frames, setFrames] = useState<ScanFrame[]>([]);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [roomShellUrl, setRoomShellUrl] = useState<string | null>(null);
  const [modelFormat, setModelFormat] = useState<"stl" | "glb">("stl");
  const [previewMode, setPreviewMode] = useState<PreviewMode>("texture");
  const [projects, setProjects] = useState<Project[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [exteriorFrameUrls, setExteriorFrameUrls] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client || !id) return;
    try {
      const [current, savedFrames] = await Promise.all([
        client.getScan(id),
        client.listScanFrames(id),
      ]);
      setScan(current);
      setFrames(savedFrames);
      // checkpoint_stage drives the "what will resume actually skip" hint, so it's only
      // worth fetching while that hint is shown (paused) or about to be (reconstructing).
      if (current.job_id && (current.status === "paused" || current.status === "reconstructing")) {
        setJob(await client.getJob(current.job_id));
      } else if (current.status !== "paused" && current.status !== "reconstructing") {
        setJob(null);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [client, id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Reconstruction runs in the background; poll while it does.
  useEffect(() => {
    if (!scan || scan.status !== "reconstructing") return;
    const timer = setInterval(() => void refresh(), 3000);
    return () => clearInterval(timer);
  }, [refresh, scan]);

  async function pause() {
    if (!client || !scan) return;
    setBusy("Pausing");
    setError(null);
    try {
      setScan(await client.pauseScan(scan.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function resume() {
    if (!client || !scan) return;
    setBusy("Resuming");
    setError(null);
    try {
      setScan(await client.resumeScan(scan.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    if (!client || !scan?.mesh_asset_id) {
      setModelUrl(null);
      setModelFormat("stl");
      return;
    }
    let cancelled = false;
    setModelUrl(null);
    void client.download(scan.mesh_asset_id).then((download) => {
      if (cancelled) return;
      setModelUrl(download.url);
      setModelFormat(download.format === "glb" ? "glb" : "stl");
    });
    return () => {
      cancelled = true;
    };
  }, [client, scan?.mesh_asset_id]);

  useEffect(() => {
    if (!client || !scan?.room_shell_asset_id) {
      setRoomShellUrl(null);
      setPreviewMode((current) => (current === "empty" ? "mesh" : current));
      return;
    }
    let cancelled = false;
    void client.download(scan.room_shell_asset_id).then((download) => {
      if (!cancelled) setRoomShellUrl(download.url);
    });
    return () => { cancelled = true; };
  }, [client, scan?.room_shell_asset_id]);

  useEffect(() => {
    if (!client || !session || scan?.project_id) return;
    void client.listProjects(session.workspaceId).then(setProjects).catch(() => undefined);
  }, [client, session, scan?.project_id]);

  useEffect(() => {
    const provider = ((scan?.report ?? {}) as Report).provider;
    if (!client || (provider !== "colmap_exterior" && provider !== "colmap_room")) {
      setExteriorFrameUrls({});
      return;
    }
    let cancelled = false;
    const sections = provider === "colmap_room" ? EXTERIOR_SECTIONS.slice(0, 4) : EXTERIOR_SECTIONS;
    const representatives = sections.flatMap((section) => {
      const frame = frames.find((candidate) =>
        provider === "colmap_room"
          ? candidate.pose.room_section === section
          : candidate.pose.exterior_section === section,
      );
      return frame ? [[section, frame.asset_id] as const] : [];
    });
    void Promise.all(
      representatives.map(async ([section, assetId]) => [section, (await client.download(assetId)).url] as const),
    )
      .then((entries) => {
        if (!cancelled) setExteriorFrameUrls(Object.fromEntries(entries));
      })
      .catch(() => {
        if (!cancelled) setExteriorFrameUrls({});
      });
    return () => {
      cancelled = true;
    };
  }, [client, frames, scan?.report]);

  async function keep(projectId?: string) {
    if (!client || !scan) return;
    setBusy("Saving");
    setError(null);
    try {
      const saved = await client.acceptScan(scan.id, { project_id: projectId ?? null });
      setScan(saved);
      if (saved.project_id) router.replace(`/project/${saved.project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function retry() {
    if (!client || !scan) return;
    setBusy("Discarding");
    try {
      await client.cancelScan(scan.id);
      router.replace("/scan");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(null);
    }
  }

  const report = (scan?.report ?? {}) as Report;
  const hasTexture = modelFormat === "glb" && report.texture?.texture_baked === true;
  const frameWarnings = scanFrameWarnings(frames);
  const scale = report.scale;
  const exterior = report.provider === "colmap_exterior" ? report.multi_view : null;
  const photoRoom = report.provider === "colmap_room" ? report.multi_view : null;
  const assembly = exterior ?? photoRoom;
  const captureStats = scan?.capture_stats as {
    room_plan?: RoomPlanStats;
    objects?: number;
  } | undefined;
  const shellSpec = captureStats?.room_plan?.room_shell;
  const shellWidth = shellSpec?.outline_mm?.length
    ? Math.max(...shellSpec.outline_mm.map((point) => point[0])) - Math.min(...shellSpec.outline_mm.map((point) => point[0]))
    : null;
  const shellDepth = shellSpec?.outline_mm?.length
    ? Math.max(...shellSpec.outline_mm.map((point) => point[1])) - Math.min(...shellSpec.outline_mm.map((point) => point[1]))
    : null;
  const wallCount = captureStats?.room_plan?.floor_plan?.walls?.length
    ?? shellSpec?.outline_mm?.length
    ?? null;
  const openingCount = captureStats?.room_plan?.floor_plan?.openings?.length
    ?? shellSpec?.openings?.length
    ?? null;
  const itemCount = typeof captureStats?.objects === "number" ? captureStats.objects : null;
  const floorAreaM2 = polygonAreaM2(shellSpec?.outline_mm);
  const reconstructionProgress = Math.max(0, Math.min(job?.progress ?? 0, 100));
  const reconstructionSteps = [
    { label: "Проверяем исходные кадры", done: reconstructionProgress >= 10 },
    { label: "Собираем геометрию", done: reconstructionProgress >= 45 || job?.checkpoint_stage === "reconstructed" },
    { label: "Оптимизируем сетку", done: reconstructionProgress >= 75 },
    { label: "Готовим превью", done: reconstructionProgress >= 95 },
  ];
  const confidenceColour =
    !scale || scale.confidence < 0.3
      ? colors.red
      : scale.confidence < 0.7
        ? colors.yellow
        : colors.green;

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: scan?.label ?? "Scan" }} />

      {scan?.status === "reconstructing" && (
        <View style={resultStyles.processingCard} accessibilityLabel="Обработка скана">
          <View style={resultStyles.processingGlyph}>
            <Text style={resultStyles.processingGlyphText}>◇</Text>
          </View>
          <View style={resultStyles.centeredCopy}>
            <Text style={styles.sectionTitle}>Создаём 3D-модель</Text>
            <Text style={styles.sectionSubtitle}>
              Обрабатываем {scan.frame_count} кадров. Можно закрыть экран — процесс продолжится.
            </Text>
          </View>
          <View style={resultStyles.progressHeader}>
            <Text style={styles.heading}>{job?.stage ?? "Обработка скана"}</Text>
            <Text style={resultStyles.progressValue}>{Math.round(reconstructionProgress)}%</Text>
          </View>
          <View style={resultStyles.progressTrack}>
            <View style={[resultStyles.progressFill, { width: `${reconstructionProgress}%` }]} />
          </View>
          <View style={resultStyles.checklist}>
            {reconstructionSteps.map((step) => (
              <View key={step.label} style={resultStyles.checklistRow}>
                <View style={[resultStyles.checkDot, step.done && resultStyles.checkDotDone]}>
                  <Text style={[resultStyles.checkMark, step.done && resultStyles.checkMarkDone]}>
                    {step.done ? "✓" : "·"}
                  </Text>
                </View>
                <Text style={[styles.text, !step.done && { color: colors.muted }]}>{step.label}</Text>
              </View>
            ))}
          </View>
          <Pressable
            style={[styles.button, resultStyles.secondaryAction, busy ? { opacity: 0.5 } : null]}
            disabled={Boolean(busy)}
            onPress={() => void pause()}
          >
            <Text style={styles.buttonText}>
              {busy === "Pausing" ? "Приостанавливаем…" : "Приостановить"}
            </Text>
          </Pressable>
        </View>
      )}

      {scan?.status === "paused" && (
        <View style={styles.card}>
          <Text style={[styles.heading, { color: colors.yellow }]}>Paused</Text>
          <Text style={styles.muted}>
            {job?.checkpoint_stage === "reconstructed"
              ? "Resuming will skip reconstruction and continue from the saved mesh."
              : "Resuming will start reconstruction over."}
          </Text>
          <Pressable
            style={[styles.button, styles.buttonPrimary, busy ? { opacity: 0.5 } : null]}
            disabled={Boolean(busy)}
            onPress={() => void resume()}
          >
            <Text style={styles.buttonText}>
              {busy === "Resuming" ? "Resuming…" : "Resume"}
            </Text>
          </Pressable>
        </View>
      )}

      {scan?.status === "failed" && (
        <View style={styles.card}>
          <Text style={styles.heading}>The scan did not reconstruct</Text>
          <Text style={styles.error}>
            {(scan.error as { message?: string } | null)?.message ?? "unknown error"}
          </Text>
          <Pressable style={[styles.button, styles.buttonPrimary]} onPress={retry}>
            <Text style={styles.buttonText}>Scan again</Text>
          </Pressable>
        </View>
      )}

      {frameWarnings.length > 0 && (
        <View style={styles.card} accessibilityLabel="Frame warnings">
          <Text style={styles.heading}>Check individual frames</Text>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ gap: 8 }}
          >
            {frameWarnings.map((warning) => (
              <View key={warning.sequenceNo} style={[styles.chip, { borderColor: colors.yellow }]}>
                <Text style={[styles.chipText, { color: colors.yellow }]}>
                  Frame {warning.sequenceNo + 1} · {warning.codes
                    .map((code) => (code === "blurry" ? "blurred" : "camera motion"))
                    .join(" · ")}
                </Text>
              </View>
            ))}
          </ScrollView>
        </View>
      )}

      {modelUrl && (
        <View style={resultStyles.previewSection} accessibilityLabel="Превью результата">
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Результат сканирования</Text>
            <Text style={styles.sectionSubtitle}>Проверьте модель перед сохранением</Text>
          </View>
          <View style={resultStyles.previewCard}>
            <View style={resultStyles.previewTabs}>
              {hasTexture && (
                <Pressable
                  style={[
                    resultStyles.previewTab,
                    previewMode === "texture" && resultStyles.previewTabActive,
                  ]}
                  onPress={() => setPreviewMode("texture")}
                >
                  <Text style={[resultStyles.previewTabText, previewMode === "texture" && resultStyles.previewTabTextActive]}>
                    Фото
                  </Text>
                </Pressable>
              )}
              <Pressable
                style={[
                  resultStyles.previewTab,
                  (previewMode === "mesh" || !hasTexture) && resultStyles.previewTabActive,
                ]}
                onPress={() => setPreviewMode("mesh")}
              >
                <Text style={[resultStyles.previewTabText, (previewMode === "mesh" || !hasTexture) && resultStyles.previewTabTextActive]}>
                  3D-модель
                </Text>
              </Pressable>
              {roomShellUrl && (
                <Pressable
                  accessibilityLabel="Показать пустую оболочку RoomPlan"
                  style={[
                    resultStyles.previewTab,
                    previewMode === "empty" && resultStyles.previewTabActive,
                  ]}
                  onPress={() => setPreviewMode("empty")}
                >
                  <Text style={[resultStyles.previewTabText, previewMode === "empty" && resultStyles.previewTabTextActive]}>
                    Без мебели
                  </Text>
                </Pressable>
              )}
            </View>
            <View style={resultStyles.viewerFrame}>
              <ModelViewer
                url={previewMode === "empty" ? roomShellUrl : modelUrl}
                format={previewMode === "empty" ? "stl" : modelFormat}
                appearance={hasTexture && previewMode === "texture" ? "source" : "mesh"}
                bodyId="scan"
                selected={false}
                onSelect={() => {}}
              />
            </View>
            <Text style={styles.sectionSubtitle}>
              {previewMode === "empty"
                ? "Точная оболочка стен и пола RoomPlan без мебели и деталей поверхностей."
                : hasTexture && previewMode === "texture"
                  ? "Фототекстура реконструкции — поверните модель и проверьте швы."
                  : "Сетка результата — проверьте отверстия, шум и плотность геометрии."}
            </Text>
            {previewMode === "empty" && shellWidth !== null && shellDepth !== null && shellSpec?.wall_height_mm && (
              <Text style={resultStyles.dimensionText} accessibilityLabel="Размеры оболочки комнаты">
                {(shellWidth / 1000).toFixed(2)} × {(shellDepth / 1000).toFixed(2)} × {(shellSpec.wall_height_mm / 1000).toFixed(2)} м
              </Text>
            )}
          </View>
        </View>
      )}

      {scan?.status === "ready" && assembly && (
        <View style={[styles.card, { gap: 10 }]} accessibilityLabel={photoRoom ? "Photo room assembly review" : "Exterior assembly review"}>
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <Text style={styles.heading}>{photoRoom ? "Photo room review" : "Building assembly review"}</Text>
            <View style={[styles.chip, { borderColor: colors.green }]}>
              <Text style={[styles.chipText, { color: colors.green }]}>connected · passed</Text>
            </View>
          </View>
          <Text style={styles.muted}>
            {assembly.registered_images ?? 0}/{report.capture?.frames ?? scan.frame_count} photos joined one camera solution · {Math.round((assembly.registered_fraction ?? report.coverage ?? 0) * 100)}% registered
            {assembly.mean_reprojection_error_px != null
              ? ` · ${assembly.mean_reprojection_error_px.toFixed(2)} px reprojection error`
              : ""}
          </Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
            {EXTERIOR_SECTIONS.filter((section) => !photoRoom || section !== "roof").filter((section) => {
              const provenance = assembly.section_provenance?.[section];
              return Boolean(provenance?.captured_sequence_nos?.length || assembly.registered_by_section?.[section]);
            }).map((section) => {
              const captured = assembly.section_provenance?.[section]?.captured_sequence_nos?.length ?? 0;
              const registered = assembly.registered_by_section?.[section] ?? 0;
              const required = section !== "roof";
              const passed = !required || registered >= 3;
              return (
                <View key={section} style={[styles.card, { width: 142, gap: 4, borderColor: passed ? colors.green : colors.red }]}>
                  {exteriorFrameUrls[section] ? (
                    <Image
                      source={{ uri: exteriorFrameUrls[section] }}
                      style={{ width: 116, height: 76, borderRadius: 8, backgroundColor: colors.viewport }}
                      accessibilityLabel={`${section} source frame`}
                    />
                  ) : null}
                  <Text style={styles.text}>{section.toUpperCase()}</Text>
                  <Text style={styles.muted}>{registered}/{captured} registered</Text>
                  {assembly.section_alignment_error_deg?.[section] != null ? (
                    <Text style={styles.muted}>
                      alignment {assembly.section_alignment_error_deg[section]?.toFixed(1)}°
                    </Text>
                  ) : null}
                </View>
              );
            })}
          </ScrollView>
          <View style={styles.row}>
            <View style={[styles.chip, { borderColor: colors.green }]}>
              <Text style={[styles.chipText, { color: colors.green }]}>metric scale applied</Text>
            </View>
            <View style={[styles.chip, { borderColor: report.texture?.texture_baked ? colors.green : colors.yellow }]}>
              <Text style={[styles.chipText, { color: report.texture?.texture_baked ? colors.green : colors.yellow }]}>
                {report.texture?.texture_baked ? "photo texture baked" : "texture unavailable"}
              </Text>
            </View>
          </View>
          <Text style={styles.muted}>
            {assembly.sparse_points?.toLocaleString() ?? "—"} sparse points · {assembly.isolated_components_removed ?? 0} isolated components removed. {photoRoom ? "Scale comes from your measured maximum span, not LiDAR. " : ""}Rotate the assembled model above before keeping it.
          </Text>
        </View>
      )}

      {scan?.status === "ready" && (
        <View style={resultStyles.statsSection} accessibilityLabel="Статистика скана">
          <Text style={styles.sectionTitle}>Что распознано</Text>
          <View style={resultStyles.statsGrid}>
            {[
              { glyph: "▥", value: wallCount ?? "—", label: "Стены" },
              { glyph: "▯", value: openingCount ?? "—", label: "Проёмы" },
              { glyph: "◇", value: itemCount ?? "—", label: "Предметы" },
              { glyph: "⌗", value: floorAreaM2 === null ? "—" : floorAreaM2.toFixed(1), label: "Площадь, м²" },
            ].map((stat) => (
              <View key={stat.label} style={resultStyles.statCard}>
                <Text style={resultStyles.statGlyph}>{stat.glyph}</Text>
                <Text style={resultStyles.statValue}>{stat.value}</Text>
                <Text style={styles.sectionSubtitle}>{stat.label}</Text>
              </View>
            ))}
          </View>
        </View>
      )}

      {scale && (
        <View style={[styles.card, resultStyles.detailCard]}>
          <Text style={styles.heading}>Масштаб</Text>
          <Text style={styles.text}>
            {scale.applied_mm.toFixed(1)} мм ·{" "}
            <Text style={{ color: confidenceColour }}>
              {scale.source === "depth"
                ? "измерено датчиком глубины"
                : scale.source === "user_measured_room_span"
                  ? "по измеренному пролёту комнаты"
                  : scale.source === "measured_max_dimension"
                    ? "по измеренному пролёту здания"
                : scale.source === "scale_hint"
                  ? "по указанному размеру"
                  : "ориентировочно"}
            </Text>
          </Text>
          {scale.warning && <Text style={[styles.muted, { color: colors.yellow }]}>{scale.warning}</Text>}
        </View>
      )}

      {scan?.status === "ready" && (
        <View style={[styles.card, resultStyles.detailCard]}>
          <Text style={styles.heading}>Съёмка</Text>
          <Text style={styles.muted}>
            {report.capture?.frames ?? scan.frame_count} кадров ·{" "}
            покрытие {Math.round((report.coverage ?? 0) * 100)}%
            {report.capture?.blurry_frames ? ` · размытых кадров: ${report.capture.blurry_frames}` : ""}
          </Text>
          {report.mask?.mask_applied === true && (
            <Text style={[styles.muted, { color: colors.green }]}>
              Фон удалён перед реконструкцией · кадров: {report.mask.frames_masked ?? "—"}
            </Text>
          )}
          {report.placeholder && <Text style={styles.muted}>{report.note}</Text>}
        </View>
      )}

      {scan?.status === "ready" && (
        <View style={resultStyles.actionsCard}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Модель готова</Text>
            <Text style={styles.sectionSubtitle}>Сохраните результат или продолжите работу в редакторе</Text>
          </View>
          {scan.project_id ? (
            <Pressable
              style={[styles.button, styles.buttonPrimary, resultStyles.primaryAction, busy ? { opacity: 0.5 } : null]}
              disabled={Boolean(busy)}
              onPress={() => keep()}
            >
              <Text style={styles.buttonText}>Открыть в редакторе</Text>
            </Pressable>
          ) : (
            projects.map((project) => (
              <Pressable
                key={project.id}
                style={[styles.button, resultStyles.projectAction, busy ? { opacity: 0.5 } : null]}
                disabled={Boolean(busy)}
                onPress={() => keep(project.id)}
              >
                <Text style={styles.buttonText}>Сохранить в «{project.name}»</Text>
              </Pressable>
            ))
          )}
          <Pressable style={[styles.button, resultStyles.secondaryAction]} disabled={Boolean(busy)} onPress={retry}>
            <Text style={[styles.buttonText, { color: colors.muted }]}>Удалить и переснять</Text>
          </Pressable>
        </View>
      )}

      {error && <Text style={styles.error}>{error}</Text>}
    </ScrollView>
  );
}

const resultStyles = StyleSheet.create({
  processingCard: {
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radii.hero,
    paddingHorizontal: 20,
    paddingVertical: 24,
    gap: 18,
    ...elevationHigh,
  },
  processingGlyph: {
    width: 72,
    height: 72,
    borderRadius: 36,
    alignSelf: "center",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.accentWashStrong,
    borderColor: colors.accent,
    borderWidth: 1,
  },
  processingGlyphText: { color: colors.accent, fontSize: 36, lineHeight: 40, fontWeight: "700" },
  centeredCopy: { alignItems: "center", gap: 6 },
  progressHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  progressValue: { color: colors.accent, fontSize: 15, fontWeight: "800" },
  progressTrack: {
    height: 8,
    overflow: "hidden",
    borderRadius: radii.pill,
    backgroundColor: colors.panel2,
  },
  progressFill: { height: "100%", borderRadius: radii.pill, backgroundColor: colors.accent },
  checklist: { gap: 10 },
  checklistRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  checkDot: {
    width: 24,
    height: 24,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    borderColor: colors.border,
    borderWidth: 1,
    backgroundColor: colors.panel2,
  },
  checkDotDone: { borderColor: colors.green, backgroundColor: colors.greenWash },
  checkMark: { color: colors.muted, fontSize: 14, fontWeight: "800" },
  checkMarkDone: { color: colors.green },
  previewSection: { gap: 12 },
  previewCard: {
    overflow: "hidden",
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radii.feature,
    padding: 10,
    gap: 10,
    ...elevationHigh,
  },
  previewTabs: {
    flexDirection: "row",
    padding: 3,
    gap: 3,
    borderRadius: radii.control,
    backgroundColor: colors.bg,
  },
  previewTab: {
    flex: 1,
    minHeight: 38,
    paddingHorizontal: 8,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radii.preview,
  },
  previewTabActive: { backgroundColor: colors.panel2 },
  previewTabText: { color: colors.muted, fontSize: 12, fontWeight: "700" },
  previewTabTextActive: { color: colors.accent },
  viewerFrame: { overflow: "hidden", borderRadius: radii.preview, backgroundColor: colors.viewport },
  dimensionText: { color: colors.text, fontSize: 13, fontWeight: "700" },
  statsSection: { gap: 12 },
  statsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  statCard: {
    width: "48%",
    minHeight: 112,
    padding: 14,
    justifyContent: "space-between",
    borderRadius: radii.section,
    borderColor: colors.border,
    borderWidth: 1,
    backgroundColor: colors.panel,
    ...elevationLow,
  },
  statGlyph: { color: colors.accent, fontSize: 19, fontWeight: "700" },
  statValue: { color: colors.text, fontSize: 24, lineHeight: 29, fontWeight: "800", letterSpacing: -0.4 },
  detailCard: { borderRadius: radii.section, ...elevationLow },
  actionsCard: {
    padding: 16,
    gap: 10,
    borderRadius: radii.feature,
    borderColor: colors.border,
    borderWidth: 1,
    backgroundColor: colors.panel,
    ...elevationHigh,
  },
  primaryAction: { minHeight: 50, justifyContent: "center" },
  projectAction: { minHeight: 48, justifyContent: "center" },
  secondaryAction: { backgroundColor: "transparent" },
});
