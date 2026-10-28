import type { FacadeCompatibility, Listing, PhysicalAiClient, Project } from "@physical-ai/contracts";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { colors, styles } from "./theme";

const SIZE_TOLERANCE_MM = 1;

function measuredSize(value: unknown): [number, number, number] | null {
  return Array.isArray(value) && value.length === 3 && value.every((item) => Number.isFinite(item) && item > 0)
    ? [value[0], value[1], value[2]] : null;
}

function sameSize(left: number[], right: number[]) {
  return left.length === 3 && right.length === 3 && left.every((value, index) => value === right[index]);
}

export function verifiedFacadeCompatibility(report: FacadeCompatibility, project: Project | undefined, listing: Listing) {
  if (!project?.head_version_id || report.project_id !== project.id || report.project_name !== project.name
    || report.version_id !== project.head_version_id || !Number.isInteger(report.total_openings)
    || !Number.isInteger(report.matched_openings) || report.total_openings !== report.openings.length) return null;
  const members = new Map<string, { label: string; size: [number, number, number] }>();
  const versionIds = new Set<string>([listing.version_id]);
  const anchorSize = measuredSize(listing.summary?.size_mm);
  if (anchorSize) members.set(listing.version_id, { label: listing.title, size: anchorSize });
  for (const component of listing.components ?? []) {
    const size = measuredSize(component.summary?.size_mm);
    if (versionIds.has(component.version_id)) return null;
    versionIds.add(component.version_id);
    if (size) members.set(component.version_id, { label: component.label, size });
  }
  const openingIds = new Set<string>();
  for (const opening of report.openings) {
    if (!opening.opening_id || openingIds.has(opening.opening_id) || !Number.isFinite(opening.width_mm) || opening.width_mm <= 0
      || !Number.isFinite(opening.height_mm) || opening.height_mm <= 0 || !Array.isArray(opening.matches)) return null;
    openingIds.add(opening.opening_id);
    const matchIds = new Set<string>();
    for (const match of opening.matches) {
      const member = members.get(match.version_id);
      const size = measuredSize(match.size_mm);
      if (!member || !size || matchIds.has(match.version_id) || match.label !== member.label || !sameSize(size, member.size)) return null;
      matchIds.add(match.version_id);
      const [, first, second] = [...size].sort((left, right) => left - right);
      const wanted = [opening.width_mm, opening.height_mm].sort((left, right) => left - right);
      if (Math.abs(first - wanted[0]) > SIZE_TOLERANCE_MM || Math.abs(second - wanted[1]) > SIZE_TOLERANCE_MM) return null;
    }
  }
  const matched = report.openings.filter((opening) => opening.matches.length > 0).length;
  const expected = report.openings.length === 0 ? "unsupported" : matched === report.openings.length ? "complete" : matched > 0 ? "partial" : "incompatible";
  return report.matched_openings === matched && report.status === expected ? report : null;
}

export function MarketplaceFacadeCompatibility({ client, workspaceId, listing }: { client: PhysicalAiClient; workspaceId: string; listing: Listing }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [report, setReport] = useState<FacadeCompatibility | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void client.listProjects(workspaceId).then((rows) => {
      if (cancelled) return;
      const candidates = rows.filter((project) => project.head_version_id);
      setProjects(candidates);
      setProjectId((current) => candidates.some((project) => project.id === current) ? current : candidates[0]?.id ?? "");
    }).catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [client, workspaceId]);

  useEffect(() => {
    const project = projects.find((candidate) => candidate.id === projectId);
    if (!project) { setReport(null); return; }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void client.facadeCompatibility(listing.id, project.id).then((value) => {
      if (cancelled) return;
      const verified = verifiedFacadeCompatibility(value, project, listing);
      setReport(verified);
      if (!verified) setError("Отчёт совместимости не совпадает с выбранной head-версией.");
    }).catch((reason: unknown) => {
      if (!cancelled) { setReport(null); setError(reason instanceof Error ? reason.message : String(reason)); }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [client, listing, projectId, projects]);

  const tone = report?.status === "complete" ? colors.green : report?.status === "partial" ? colors.yellow : colors.red;
  return (
    <View style={[styles.card, { gap: 10 }]} accessibilityLabel="Совместимость с фасадом">
      <Text style={styles.heading}>Совместимость с фасадом</Text>
      {projects.length > 0 ? <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>{projects.map((project) => <Pressable key={project.id} accessibilityRole="radio" accessibilityState={{ checked: project.id === projectId }} onPress={() => setProjectId(project.id)} style={[styles.chip, project.id === projectId && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}><Text style={[styles.chipText, project.id === projectId && { color: colors.accent }]}>{project.name}</Text></Pressable>)}</ScrollView> : !loading ? <Text style={styles.sectionSubtitle}>Нет проекта с сохранённой моделью.</Text> : null}
      {loading ? <Text style={styles.sectionSubtitle}>Проверяем сохранённые проёмы…</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {report?.status === "unsupported" ? <Text style={styles.sectionSubtitle}>Выбранный проект должен иметь сохранённый exact-фасад с адресными проёмами.</Text> : null}
      {report && report.status !== "unsupported" ? <View style={{ gap: 8 }}>
        <Text style={[styles.heading, { color: tone }]}>{report.matched_openings} из {report.total_openings} проёмов совпадают по габаритам</Text>
        {report.openings.map((opening) => <View key={opening.opening_id} style={[styles.row, { justifyContent: "space-between", alignItems: "flex-start", gap: 8 }]}><View style={{ flex: 1 }}><Text style={styles.heading}>{opening.side} · этаж {opening.floor ?? "—"}</Text><Text style={styles.sectionSubtitle}>{opening.width_mm.toFixed(0)} × {opening.height_mm.toFixed(0)} мм</Text></View><Text style={[styles.sectionSubtitle, { color: opening.matches.length > 0 ? colors.green : colors.muted, textAlign: "right", flex: 1 }]}>{opening.matches.length > 0 ? opening.matches.map((match) => match.label).join(", ") : "Нет подходящего модуля"}</Text></View>)}
        <Text style={styles.sectionSubtitle}>Проверены сохранённые габариты модулей и адреса проёмов. Крепёж, направление монтажа, зазор и mesh-коллизии проверяются отдельно после получения.</Text>
      </View> : null}
    </View>
  );
}
