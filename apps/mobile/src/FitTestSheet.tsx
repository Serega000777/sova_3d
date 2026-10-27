/** Mobile reachability for the existing exact assembly/fit-test pipeline (F-027). */
import type {
  FitTestBody,
  FitTestReport,
  PhysicalAiClient,
  Project,
} from "@physical-ai/contracts";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, radii, styles } from "./theme";

const FITS: FitTestBody["wanted"][] = ["clearance", "sliding", "transition", "press"];

const RU_FIT: Record<string, string> = {
  clearance: "с зазором",
  sliding: "скользящая",
  transition: "переходная",
  press: "плотная",
  collides: "пересечение",
  loose: "слишком свободная",
  apart: "не соприкасаются",
};

export function FitTestSheet({
  visible,
  language,
  client,
  workspaceId,
  currentProjectId,
  versionId,
  onClose,
  onApplyFix,
  onCreatedAssembly,
}: {
  visible: boolean;
  language: "ru" | "en";
  client: PhysicalAiClient | null;
  workspaceId: string | null;
  currentProjectId: string | null;
  versionId: string | null;
  onClose: () => void;
  onApplyFix: (fix: NonNullable<FitTestReport["advice"]["fix"]>) => Promise<void>;
  onCreatedAssembly: (versionId: string) => Promise<void>;
}) {
  const ru = language === "ru";
  const [projects, setProjects] = useState<Project[]>([]);
  const [otherId, setOtherId] = useState("");
  const [wanted, setWanted] = useState<FitTestBody["wanted"]>("sliding");
  const [report, setReport] = useState<FitTestReport | null>(null);
  const [fitTestId, setFitTestId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!visible || !client || !workspaceId) return;
    let cancelled = false;
    setError(null);
    void client
      .listProjects(workspaceId)
      .then((rows) => {
        if (cancelled) return;
        const candidates = rows.filter(
          (project) => project.id !== currentProjectId && project.head_version_id,
        );
        setProjects(candidates);
        setOtherId((current) =>
          candidates.some((project) => project.id === current) ? current : candidates[0]?.id ?? "",
        );
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [visible, client, workspaceId, currentProjectId]);

  useEffect(() => {
    setReport(null);
    setFitTestId(null);
  }, [versionId, otherId]);

  const chosen = projects.find((project) => project.id === otherId) ?? null;

  async function run() {
    if (!client || !versionId || !chosen?.head_version_id) return;
    setBusy(true);
    setError(null);
    try {
      const accepted = await client.startFitTest({
        version_a_id: versionId,
        version_b_id: chosen.head_version_id,
        placement: {
          align: "centre",
          offset_mm: [0, 0, 0],
          rotate_x_deg: 0,
          rotate_y_deg: 0,
          rotate_z_deg: 0,
        },
        auto_place: true,
        wanted,
        language,
      });
      const job = await client.waitForJob(accepted.job_id, { timeoutMs: 8 * 60_000 });
      if (job.status !== "succeeded") {
        throw new Error(
          (job.error as { message?: string } | null)?.message ??
            (ru ? "Не удалось проверить посадку." : "The fit test failed."),
        );
      }
      const result = job.result as { fit_test_id?: string; report?: FitTestReport } | null;
      if (!result?.report?.measured || !result.report.advice) {
        throw new Error(ru ? "Сервер вернул неполный отчёт посадки." : "The server returned an incomplete fit report.");
      }
      setReport(result.report);
      setFitTestId(result.fit_test_id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  const measured = report?.measured;
  const advice = report?.advice;
  const resultTone = measured?.verdict === "collides"
    ? colors.red
    : measured?.verdict === "apart" || measured?.verdict === "loose"
      ? colors.yellow
      : colors.green;

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="92%"
      tabletWidth={600}
      accessibilityLabel={ru ? "Закрыть проверку посадки" : "Close fit test"}
      contentGap={12}
    >
      <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 12 }}>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.title}>{ru ? "Проверка посадки" : "Fit test"}</Text>
          <Text style={styles.sectionSubtitle}>
            {ru
              ? "Выберите вторую деталь. Сервер проверит центр, четыре поворота и касание каждой гранью."
              : "Choose the second part. The server checks the centre, four rotations and every touching face."}
          </Text>
        </View>
        <Pressable accessibilityLabel={ru ? "Закрыть" : "Close"} hitSlop={12} onPress={onClose}>
          <Text style={[styles.sectionTitle, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={{ gap: 14 }} showsVerticalScrollIndicator={false}>
        {projects.length ? (
          <>
            <View style={{ gap: 8 }}>
              <Text style={styles.heading}>{ru ? "Вторая деталь" : "Second part"}</Text>
              <View style={{ gap: 7 }}>
                {projects.map((project) => {
                  const selected = project.id === otherId;
                  return (
                    <Pressable
                      key={project.id}
                      accessibilityRole="radio"
                      accessibilityState={{ checked: selected }}
                      onPress={() => setOtherId(project.id)}
                      style={[styles.button, selected && { borderColor: colors.accent, backgroundColor: colors.accentWash }]}
                    >
                      <Text style={[styles.buttonText, selected && { color: colors.accent }]}>{project.name}</Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>

            <View style={{ gap: 8 }}>
              <Text style={styles.heading}>{ru ? "Нужная посадка" : "Target fit"}</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 7 }}>
                {FITS.map((fit) => {
                  const selected = fit === wanted;
                  return (
                    <Pressable
                      key={fit}
                      accessibilityRole="radio"
                      accessibilityState={{ checked: selected }}
                      onPress={() => setWanted(fit)}
                      style={[styles.chip, selected && { borderColor: colors.selection, backgroundColor: colors.accentWash }]}
                    >
                      <Text style={[styles.chipText, selected && { color: colors.selection }]}>
                        {ru ? RU_FIT[fit] : fit}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>

            <Pressable
              disabled={busy || !chosen || !versionId}
              onPress={() => void run()}
              style={[styles.button, styles.buttonPrimary, { minHeight: 52 }, (busy || !chosen || !versionId) && { opacity: 0.48 }]}
            >
              <Text style={styles.buttonText}>{busy ? (ru ? "Проверяем…" : "Checking…") : (ru ? "Проверить совместимость" : "Check compatibility")}</Text>
            </Pressable>
          </>
        ) : (
          <Text style={styles.muted}>
            {ru
              ? "Нужен второй проект с готовой 3D-моделью. Он используется как деталь B и не изменяется."
              : "A second project with a ready 3D model is required. It is used as part B and is not changed."}
          </Text>
        )}

        {error && <Text style={[styles.muted, { color: colors.red }]}>{error}</Text>}

        {measured && advice && (
          <View style={{ gap: 9, padding: 13, borderRadius: radii.section, borderWidth: 1, borderColor: resultTone, backgroundColor: colors.panel2 }}>
            <Text style={[styles.heading, { color: resultTone }]}>
              {ru ? RU_FIT[measured.verdict] ?? measured.verdict : measured.verdict}
            </Text>
            <Text style={styles.text}>{advice.summary}</Text>
            {measured.placement && (
              <Text style={styles.muted}>
                {ru ? "Положение B" : "Part B position"}: {measured.placement.offset_mm.map((value) => Number(value).toFixed(1)).join(" · ")} {ru ? "мм" : "mm"} · X/Y/Z {measured.placement.rotate_x_deg ?? 0}°/{measured.placement.rotate_y_deg ?? 0}°/{measured.placement.rotate_z_deg}°
              </Text>
            )}
            <Text style={styles.muted}>
              {measured.max_penetration_mm > 0
                ? `${ru ? "Пересечение" : "Overlap"}: ${measured.max_penetration_mm} ${ru ? "мм на сторону" : "mm per side"}`
                : measured.min_clearance_mm !== null
                  ? `${ru ? "Зазор" : "Gap"}: ${measured.min_clearance_mm} ${ru ? "мм на сторону" : "mm per side"}`
                  : ru ? "Числовой зазор не определён" : "No numeric clearance was determined"}
            </Text>
            {advice.recommendation && <Text style={styles.text}>{advice.recommendation}</Text>}
            {advice.fix && (
              <Pressable disabled={busy} style={[styles.button, styles.buttonPrimary]} onPress={() => void onApplyFix(advice.fix!)}>
                <Text style={styles.buttonText}>{ru ? "Применить исправление" : "Apply fix"}: {advice.fix.label}</Text>
              </Pressable>
            )}
            {fitTestId && measured.verdict !== "collides" && (
              <Pressable
                disabled={busy}
                style={[styles.button, styles.buttonPrimary]}
                onPress={() => {
                  if (!client) return;
                  setBusy(true);
                  setError(null);
                  void client.createFitAssembly(fitTestId)
                    .then((scene) => onCreatedAssembly(scene.version_id))
                    .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)))
                    .finally(() => setBusy(false));
                }}
              >
                <Text style={styles.buttonText}>
                  {ru ? "Сохранить как сборку" : "Save as assembly"}
                </Text>
              </Pressable>
            )}
            <Text style={styles.sectionSubtitle}>
              {ru ? "Исправление создаст новую неизменяемую версию детали A." : "A fix creates a new immutable version of part A."}
            </Text>
          </View>
        )}
      </ScrollView>
    </SheetShell>
  );
}
