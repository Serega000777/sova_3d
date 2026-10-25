import type { Material, PrintFarmPlan, PrinterProfile, Project } from "@physical-ai/contracts";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/src/session";
import { colors, radii, styles } from "@/src/theme";

function hours(minutes: number): string {
  return `${Math.ceil(minutes / 60)} ч`;
}

export default function PrintQueueScreen() {
  const { client, session } = useSession();
  const [projects, setProjects] = useState<Project[]>([]);
  const [printers, setPrinters] = useState<PrinterProfile[]>([]);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [printerIds, setPrinterIds] = useState<string[]>([]);
  const [materialId, setMaterialId] = useState("pla");
  const [plan, setPlan] = useState<PrintFarmPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client || !session) return;
    try {
      const [allProjects, profiles, stock] = await Promise.all([
        client.listProjects(session.workspaceId),
        client.listPrinterProfiles(session.workspaceId),
        client.listMaterials(),
      ]);
      setProjects(allProjects.filter((project) => project.head_version_id));
      setPrinters(profiles);
      setMaterials(stock);
      setPrinterIds((current) => current.length > 0 ? current : profiles.map((profile) => profile.id));
      setMaterialId((current) => stock.some((material) => material.id === current) ? current : stock[0]?.id ?? "pla");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, [client, session]);

  useEffect(() => { void refresh(); }, [refresh]);

  const itemCount = useMemo(() => Object.values(quantities).reduce((sum, value) => sum + value, 0), [quantities]);

  function setQuantity(projectId: string, value: number) {
    setQuantities((current) => ({ ...current, [projectId]: Math.max(0, Math.min(50, value)) }));
    setPlan(null);
  }

  function togglePrinter(id: string) {
    setPrinterIds((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
    setPlan(null);
  }

  async function buildPlan() {
    if (!client || !session || busy) return;
    const items = projects.flatMap((project) => {
      const quantity = quantities[project.id] ?? 0;
      return project.head_version_id && quantity > 0 ? [{ version_id: project.head_version_id, quantity }] : [];
    });
    if (items.length === 0 || printerIds.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      setPlan(await client.planPrintFarm({
        workspace_id: session.workspaceId,
        items,
        printer_profile_ids: printerIds,
        material_id: materialId,
        infill_density_pct: 20,
        wall_count: 2,
        margin_mm: 5,
        gap_mm: 8,
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <View style={[styles.screen, { alignItems: "center", justifyContent: "center" }]}><ActivityIndicator color={colors.accent} /></View>;
  }

  return (
    <SafeAreaView style={styles.screen} edges={["bottom"]}>
      <ScrollView contentContainerStyle={{ width: "100%", maxWidth: 900, alignSelf: "center", padding: 16, paddingBottom: 32, gap: 14 }}>
        <View style={{ gap: 5 }}>
          <Text style={[styles.title, { fontSize: 29 }]}>Очередь печати</Text>
          <Text style={styles.muted}>Распределите выбранные проекты по реальным профилям принтеров. Это расчёт платформ и времени, а не запуск оборудования.</Text>
        </View>

        <View style={[styles.card, { borderRadius: radii.feature }]}>
          <Text style={styles.sectionTitle}>Проекты и копии</Text>
          {projects.map((project) => {
            const quantity = quantities[project.id] ?? 0;
            return (
              <View key={project.id} style={[styles.row, { justifyContent: "space-between", paddingVertical: 7, borderBottomWidth: 1, borderBottomColor: colors.border }]}>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={styles.heading}>{project.name}</Text>
                  <Text style={styles.muted}>{project.head_version_id ? `Версия ${project.head_version_id.slice(0, 8)}` : "Нет модели"}</Text>
                </View>
                <View style={styles.row}>
                  <Pressable accessibilityLabel={`Уменьшить количество ${project.name}`} onPress={() => setQuantity(project.id, quantity - 1)} style={styles.chip}><Text style={styles.chipText}>−</Text></Pressable>
                  <Text style={[styles.heading, { minWidth: 24, textAlign: "center" }]}>{quantity}</Text>
                  <Pressable accessibilityLabel={`Увеличить количество ${project.name}`} onPress={() => setQuantity(project.id, quantity + 1)} style={styles.chip}><Text style={styles.chipText}>+</Text></Pressable>
                </View>
              </View>
            );
          })}
          {projects.length === 0 ? <Text style={styles.muted}>Нет проектов с текущей 3D-версией.</Text> : null}
        </View>

        <View style={[styles.card, { borderRadius: radii.feature }]}>
          <Text style={styles.sectionTitle}>Принтеры</Text>
          <View style={styles.row}>
            {printers.map((profile) => {
              const selected = printerIds.includes(profile.id);
              return <Pressable key={profile.id} onPress={() => togglePrinter(profile.id)} style={[styles.chip, selected && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}><Text style={styles.chipText}>{selected ? "✓ " : ""}{profile.name}</Text></Pressable>;
            })}
          </View>
          <Text style={styles.sectionTitle}>Материал</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
            {materials.map((material) => <Pressable key={material.id} onPress={() => { setMaterialId(material.id); setPlan(null); }} style={[styles.chip, materialId === material.id && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}><Text style={styles.chipText}>{material.name}</Text></Pressable>)}
          </ScrollView>
          <Text style={styles.muted}>Заполнение 20% · 2 стенки · край 5 мм · зазор 8 мм. Сервер проверит габариты каждой immutable‑версии и вместимость выбранных столов.</Text>
        </View>

        {error ? <Text style={styles.error}>{error}</Text> : null}
        <Pressable disabled={busy || itemCount === 0 || printerIds.length === 0} onPress={() => void buildPlan()} style={[styles.button, styles.buttonPrimary, (busy || itemCount === 0 || printerIds.length === 0) && { opacity: 0.45 }]}>
          <Text style={styles.buttonText}>{busy ? "Распределяем…" : `Рассчитать ${itemCount} шт.`}</Text>
        </Pressable>

        {plan ? (
          <View style={{ gap: 12 }}>
            <View style={[styles.row, { alignItems: "stretch" }]}>
              <View style={[styles.card, { flex: 1, minWidth: 130 }]}><Text style={styles.sectionSubtitle}>Платформы</Text><Text style={styles.sectionTitle}>{plan.plate_count}</Text></View>
              <View style={[styles.card, { flex: 1, minWidth: 130 }]}><Text style={styles.sectionSubtitle}>До завершения</Text><Text style={styles.sectionTitle}>~{hours(plan.estimated_makespan_minutes)}</Text></View>
              <View style={[styles.card, { flex: 1, minWidth: 130 }]}><Text style={styles.sectionSubtitle}>Материал</Text><Text style={styles.sectionTitle}>{plan.estimated_material_g.toFixed(1)} г</Text><Text style={styles.muted}>{plan.estimated_material_cost.toFixed(2)} {plan.currency}</Text></View>
            </View>
            {plan.assignments.map((assignment) => (
              <View key={assignment.printer_profile_id} style={[styles.card, { borderRadius: radii.feature }]}>
                <Text style={styles.sectionTitle}>{assignment.printer_name}</Text>
                <Text style={styles.muted}>Стол {assignment.bed_mm.map((value) => Math.round(value)).join(" × ")} мм · ~{hours(assignment.estimated_minutes)}</Text>
                {assignment.plates.map((plate) => (
                  <View key={plate.number} style={{ gap: 5, paddingTop: 7, borderTopWidth: 1, borderTopColor: colors.border }}>
                    <Text style={styles.heading}>Платформа {plate.number} · ~{hours(plate.estimated_minutes)}</Text>
                    {plate.placements.map((placement) => (
                      <Text key={`${placement.version_id}-${placement.copy_number}`} style={styles.muted}>
                        {placement.project_name} · копия {placement.copy_number} · X {placement.plate_offset_mm[0].toFixed(1)} · Y {placement.plate_offset_mm[1].toFixed(1)} · {placement.plate_rotation_deg}°
                      </Text>
                    ))}
                  </View>
                ))}
              </View>
            ))}
            <View style={[styles.card, { borderColor: colors.yellow, backgroundColor: colors.yellowWash }]}>
              <Text style={[styles.heading, { color: colors.yellow }]}>План не отправлен на принтеры</Text>
              <Text style={styles.muted}>API подтверждает `dispatch_ready=false`: G-code, физическая очередь и запуск каждой платформы остаются отдельными действиями.</Text>
            </View>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
