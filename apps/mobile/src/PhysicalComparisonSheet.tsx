/** F-043: compare a digital design to a trusted metric post-print scan. */
import type { PhysicalAiClient, Project, Version } from "@physical-ai/contracts";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, radii, styles } from "./theme";

interface Candidate {
  project: Project;
  version: Version;
}

interface Report {
  registration_rms_mm: number;
  tolerance_mm: number;
  mean_mm: number;
  p95_mm: number;
  max_mm: number;
  within_tolerance: number;
  design_size_mm: number[];
  scan_size_mm: number[];
  size_error_mm: number[];
  scale_locked: boolean;
}

export function PhysicalComparisonSheet({
  visible,
  language,
  client,
  workspaceId,
  versionId,
  onClose,
}: {
  visible: boolean;
  language: "ru" | "en";
  client: PhysicalAiClient | null;
  workspaceId: string | null;
  versionId: string | null;
  onClose: () => void;
}) {
  const ru = language === "ru";
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!visible || !client || !workspaceId) return;
    let cancelled = false;
    setError(null);
    void client.listProjects(workspaceId).then(async (projects) => {
      const rows = await Promise.all(projects.map(async (project) => ({
        project,
        versions: await client.listVersions(project.id),
      })));
      if (cancelled) return;
      const scans = rows.flatMap(({ project, versions }) => versions
        .filter((version) => version.id !== versionId && version.provenance?.operation === "scan")
        .map((version) => ({ project, version })));
      setCandidates(scans);
      setSelectedId((current) => scans.some((item) => item.version.id === current)
        ? current
        : scans[0]?.version.id ?? "");
    }).catch((reason) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
    });
    return () => { cancelled = true; };
  }, [visible, client, workspaceId, versionId]);

  async function run() {
    if (!client || !versionId || !selectedId) return;
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const accepted = await client.comparePhysicalScan(versionId, {
        scan_version_id: selectedId,
        tolerance_mm: 0.2,
        samples: 3000,
      });
      const job = await client.waitForJob(accepted.job_id, { timeoutMs: 8 * 60_000 });
      if (job.status !== "succeeded") {
        throw new Error((job.error as { message?: string } | null)?.message
          ?? (ru ? "Сравнение не завершилось." : "Comparison did not complete."));
      }
      const result = job.result as { report?: Report } | null;
      if (!result?.report?.scale_locked) {
        throw new Error(ru ? "Сервер не подтвердил метрический масштаб." : "The server did not confirm metric scale.");
      }
      setReport(result.report);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SheetShell visible={visible} onClose={onClose} maxHeightPercent="92%" tabletWidth={620} accessibilityLabel={ru ? "Закрыть сравнение со сканом" : "Close scan comparison"}>
      <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 12 }}>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.title}>{ru ? "CAD ↔ напечатанная деталь" : "CAD ↔ printed part"}</Text>
          <Text style={styles.sectionSubtitle}>
            {ru
              ? "Только принятый метрический скан. Сервер совмещает позу, но не масштабирует сетку и не скрывает усадку."
              : "Accepted metric scans only. The server aligns pose but never scales the mesh or hides shrinkage."}
          </Text>
        </View>
        <Pressable accessibilityLabel={ru ? "Закрыть" : "Close"} hitSlop={12} onPress={onClose}><Text style={[styles.sectionTitle, { color: colors.muted }]}>×</Text></Pressable>
      </View>
      <ScrollView contentContainerStyle={{ gap: 12 }} showsVerticalScrollIndicator={false}>
        {candidates.map(({ project, version }) => {
          const selected = version.id === selectedId;
          return (
            <Pressable key={version.id} accessibilityRole="radio" accessibilityState={{ checked: selected }} onPress={() => { setSelectedId(version.id); setReport(null); }} style={[styles.button, selected && { borderColor: colors.accent, backgroundColor: colors.accentWash }]}>
              <Text style={[styles.buttonText, selected && { color: colors.accent }]}>{project.name} · v{version.sequence_no}</Text>
              <Text style={styles.muted}>{String(version.provenance?.mode ?? (ru ? "метрический скан" : "metric scan"))}</Text>
            </Pressable>
          );
        })}
        {candidates.length === 0 && <Text style={styles.muted}>{ru ? "Сначала примите результат метрического скана напечатанной детали." : "Accept a metric scan of the printed part first."}</Text>}
        <Pressable disabled={busy || !selectedId || !versionId} onPress={() => void run()} style={[styles.button, styles.buttonPrimary, (busy || !selectedId || !versionId) && { opacity: 0.45 }]}>
          <Text style={styles.buttonText}>{busy ? (ru ? "Совмещаем и измеряем…" : "Registering and measuring…") : (ru ? "Сравнить геометрию" : "Compare geometry")}</Text>
        </Pressable>
        {error && <Text style={[styles.muted, { color: colors.red }]}>{error}</Text>}
        {report && (
          <View style={{ gap: 8, padding: 13, borderRadius: radii.section, borderWidth: 1, borderColor: report.within_tolerance >= 0.95 ? colors.green : colors.yellow, backgroundColor: colors.panel2 }}>
            <Text style={styles.heading}>{Math.round(report.within_tolerance * 100)}% {ru ? "точек в допуске" : "of points within tolerance"} ±{report.tolerance_mm} mm</Text>
            <Text style={styles.text}>mean {report.mean_mm.toFixed(3)} · p95 {report.p95_mm.toFixed(3)} · max {report.max_mm.toFixed(3)} mm</Text>
            <Text style={styles.muted}>RMS {ru ? "совмещения" : "registration"}: {report.registration_rms_mm.toFixed(3)} mm</Text>
            <Text style={styles.muted}>{ru ? "Ошибка габаритов X/Y/Z" : "X/Y/Z size error"}: {report.size_error_mm.map((value) => `${value >= 0 ? "+" : ""}${value.toFixed(3)}`).join(" · ")} mm</Text>
          </View>
        )}
      </ScrollView>
    </SheetShell>
  );
}
