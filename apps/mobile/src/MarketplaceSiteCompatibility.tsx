import type { PhysicalAiClient, Project, SitePlanCompatibility } from "@physical-ai/contracts";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { colors, styles } from "./theme";

const EPSILON_MM = 1e-6;
const TERRAIN_TOLERANCE_MM = 1;

function finitePair(value: number[] | null, allowZero = false): value is [number, number] {
  return Array.isArray(value) && value.length === 2
    && value.every((item) => Number.isFinite(item) && (allowZero ? item >= 0 : item > 0));
}

function close(left: number, right: number, tolerance = EPSILON_MM) {
  return Math.abs(left - right) <= tolerance;
}

export function verifiedSitePlanCompatibility(report: SitePlanCompatibility, project: Project | undefined) {
  if (!project || report.project_id !== project.id || report.project_name !== project.name || report.version_id !== project.head_version_id) return null;
  const terrainAbsent = report.terrain_rotation_deg === null && report.terrain_corner_delta_mm === null && report.terrain_max_delta_mm === null;
  if (report.status === "unsupported") {
    return typeof report.reason === "string" && report.reason.length > 0
      && (report.required_size_mm === null || finitePair(report.required_size_mm))
      && report.available_size_mm === null && report.spare_size_mm === null && terrainAbsent ? report : null;
  }
  if (report.reason !== null || !finitePair(report.required_size_mm) || !finitePair(report.available_size_mm)) return null;
  const [requiredLength, requiredWidth] = report.required_size_mm;
  const [availableLength, availableWidth] = report.available_size_mm;
  const direct = [availableLength - requiredLength, availableWidth - requiredWidth] as const;
  const rotated = [availableLength - requiredWidth, availableWidth - requiredLength] as const;
  const expected = Math.min(...direct) >= 0 ? "compatible" : Math.min(...rotated) >= 0 ? "rotated" : "incompatible";
  if (report.status !== expected) return null;
  const spare = expected === "compatible" ? direct : expected === "rotated" ? rotated : null;
  if (spare === null ? report.spare_size_mm !== null : !finitePair(report.spare_size_mm, true)
    || !close(report.spare_size_mm[0], spare[0]) || !close(report.spare_size_mm[1], spare[1])) return null;
  const same = close(requiredLength, availableLength, TERRAIN_TOLERANCE_MM) && close(requiredWidth, availableWidth, TERRAIN_TOLERANCE_MM);
  const swapped = !same && close(requiredWidth, availableLength, TERRAIN_TOLERANCE_MM) && close(requiredLength, availableWidth, TERRAIN_TOLERANCE_MM);
  if (!same && !swapped) return terrainAbsent ? report : null;
  const deltas = report.terrain_corner_delta_mm;
  if (!Array.isArray(deltas) || deltas.length !== 4 || !deltas.every(Number.isFinite) || !close(deltas[0], 0)
    || report.terrain_max_delta_mm === null || !Number.isFinite(report.terrain_max_delta_mm) || report.terrain_max_delta_mm < 0
    || !close(report.terrain_max_delta_mm, Math.max(...deltas.map(Math.abs)))) return null;
  const allowed = same ? [0, 180] : [90, 270];
  return report.terrain_rotation_deg !== null && allowed.includes(report.terrain_rotation_deg) ? report : null;
}

export function MarketplaceSiteCompatibility({ client, workspaceId, listingId }: { client: PhysicalAiClient; workspaceId: string; listingId: string }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [report, setReport] = useState<SitePlanCompatibility | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void client.listProjects(workspaceId).then((rows) => {
      if (cancelled) return;
      const candidates = rows.filter((project) => project.head_version_id);
      setProjects(candidates);
      setProjectId((current) => candidates.some((project) => project.id === current) ? current : candidates[0]?.id ?? "");
    }).catch((reason: unknown) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [client, workspaceId]);

  useEffect(() => {
    const project = projects.find((candidate) => candidate.id === projectId);
    if (!project) { setReport(null); return; }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void client.sitePlanCompatibility(listingId, project.id).then((value) => {
      if (cancelled) return;
      const verified = verifiedSitePlanCompatibility(value, project);
      setReport(verified);
      if (!verified) setError("Отчёт участка не совпадает с выбранной head-версией.");
    }).catch((reason: unknown) => {
      if (!cancelled) { setReport(null); setError(reason instanceof Error ? reason.message : String(reason)); }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [client, listingId, projectId, projects]);

  const tone = report?.status === "compatible" ? colors.green : report?.status === "rotated" ? colors.yellow : colors.red;
  const status = report?.status === "compatible" ? "Композиция помещается" : report?.status === "rotated" ? "Помещается после поворота на 90°" : "Композиция не помещается";

  return (
    <View style={[styles.card, { gap: 10 }]} accessibilityLabel="Совместимость с вашим участком">
      <Text style={styles.heading}>Совместимость с вашим участком</Text>
      {projects.length > 0 ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
          {projects.map((project) => <Pressable key={project.id} accessibilityRole="radio" accessibilityState={{ checked: project.id === projectId }} onPress={() => setProjectId(project.id)} style={[styles.chip, project.id === projectId && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}><Text style={[styles.chipText, project.id === projectId && { color: colors.accent }]}>{project.name}</Text></Pressable>)}
        </ScrollView>
      ) : !loading ? <Text style={styles.sectionSubtitle}>Нет проекта с сохранённой моделью.</Text> : null}
      {loading ? <Text style={styles.sectionSubtitle}>Проверяем доказанные размеры…</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {report?.status === "unsupported" ? <Text style={styles.sectionSubtitle}>В выбранном проекте нужен участок, сохранённый успешной сборкой композиции.</Text> : null}
      {report && report.status !== "unsupported" ? (
        <View style={{ gap: 8 }}>
          <Text style={[styles.heading, { color: tone }]}>{status}</Text>
          {report.required_size_mm && report.available_size_mm ? <Text style={styles.sectionSubtitle}>{(report.required_size_mm[0] / 1000).toFixed(1)} × {(report.required_size_mm[1] / 1000).toFixed(1)} м → {(report.available_size_mm[0] / 1000).toFixed(1)} × {(report.available_size_mm[1] / 1000).toFixed(1)} м</Text> : null}
          {report.terrain_corner_delta_mm ? <View style={{ gap: 6 }}><Text style={styles.sectionSubtitle}>Профиль углов после поворота {report.terrain_rotation_deg}° · максимум {report.terrain_max_delta_mm?.toFixed(0)} мм</Text><View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>{report.terrain_corner_delta_mm.map((delta, index) => <View key={["SW", "SE", "NE", "NW"][index]} style={styles.chip}><Text style={styles.chipText}>{["SW", "SE", "NE", "NW"][index]} {delta >= 0 ? "+" : ""}{delta.toFixed(0)} мм</Text></View>)}</View></View> : null}
          <Text style={styles.sectionSubtitle}>Сравниваются размеры и, при точном контуре, профиль четырёх углов. Это не проверка нормативных отступов, земляных работ или коллизий.</Text>
        </View>
      ) : null}
    </View>
  );
}
