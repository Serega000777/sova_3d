import { ApiError, type PhysicalAiClient } from "@physical-ai/contracts";
import { useEffect, useMemo, useRef, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { verifiedAssemblyGuideProgress } from "./assembly-guide-progress";
import type { MechanismAssemblyGuide } from "./mechanism-assembly-guide";
import { colors, radii, styles } from "./theme";

export function AssemblyGuideCard({
  guide,
  versionId,
  language,
  client,
  editable,
  nodeNames,
  onSelectNode,
}: {
  guide: MechanismAssemblyGuide;
  versionId: string;
  language: "ru" | "en";
  client: PhysicalAiClient | null;
  editable: boolean;
  nodeNames: ReadonlyMap<string, string>;
  onSelectNode: (nodeId: string) => void;
}) {
  const ru = language === "ru";
  const stepIds = useMemo(() => new Set(guide.steps.map((step) => step.id)), [guide.steps]);
  const [completed, setCompleted] = useState<Set<string>>(new Set());
  const [revision, setRevision] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const requestRevision = useRef(0);

  useEffect(() => {
    const request = ++requestRevision.current;
    let cancelled = false;
    setCompleted(new Set());
    setRevision(0);
    setLoaded(false);
    setSaving(false);
    setSyncError(null);
    if (!client || !versionId) return () => { cancelled = true; };
    void client.getAssemblyGuideProgress(versionId)
      .then((progress) => {
        if (cancelled || requestRevision.current !== request) return;
        const verified = verifiedAssemblyGuideProgress(progress, versionId, guide);
        if (!verified) throw new Error("Invalid assembly guide progress response");
        setCompleted(verified.completed);
        setRevision(verified.revision);
        setLoaded(true);
      })
      .catch((reason) => {
        if (!cancelled && requestRevision.current === request) {
          setSyncError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    return () => {
      cancelled = true;
      requestRevision.current += 1;
    };
  }, [client, guide, stepIds, versionId]);

  const save = async (next: Set<string>) => {
    if (!client || !editable || !loaded || saving) return;
    const request = ++requestRevision.current;
    setSaving(true);
    setSyncError(null);
    try {
      const progress = await client.putAssemblyGuideProgress(versionId, {
        guide_kind: guide.kind,
        completed_step_ids: guide.steps.flatMap((step) => next.has(step.id) ? [step.id] : []),
        expected_revision: revision,
      });
      const verified = verifiedAssemblyGuideProgress(progress, versionId, guide);
      if (!verified) throw new Error("Invalid assembly guide progress response");
      if (requestRevision.current !== request) return;
      setCompleted(verified.completed);
      setRevision(verified.revision);
    } catch (reason) {
      if (requestRevision.current !== request) return;
      if (reason instanceof ApiError && reason.status === 409) {
        try {
          const latest = verifiedAssemblyGuideProgress(
            await client.getAssemblyGuideProgress(versionId),
            versionId,
            guide,
          );
          if (!latest || requestRevision.current !== request) {
            throw new Error("Invalid assembly guide progress response");
          }
          setCompleted(latest.completed);
          setRevision(latest.revision);
          setSyncError(ru
            ? "Отметки изменились на другом устройстве — показана свежая версия."
            : "The checklist changed on another device; the latest version is shown.");
        } catch (reloadReason) {
          if (requestRevision.current === request) {
            setSyncError(reloadReason instanceof Error ? reloadReason.message : String(reloadReason));
          }
        }
      } else {
        setSyncError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (requestRevision.current === request) setSaving(false);
    }
  };

  const toggle = (stepId: string) => {
    const next = new Set(completed);
    if (next.has(stepId)) next.delete(stepId);
    else next.add(stepId);
    void save(next);
  };

  return (
    <View
      style={styles.card}
      accessibilityLabel={ru ? "Инструкция по сборке этой версии" : "Assembly guide for this version"}
    >
      <Text style={styles.heading}>
        {ru ? "Инструкция по сборке этой версии" : "Assembly guide for this version"}
      </Text>
      <Text style={styles.muted}>
        {ru
          ? "Шаги показаны только после сверки деталей механизма с ведомостью этой неизменяемой версии. Нажмите деталь, чтобы выделить её в сцене."
          : "Steps appear only after matching the mechanism parts to this immutable version's bill of materials. Press a part to select it in the scene."}
      </Text>
      <View style={{ gap: 5 }} accessibilityLabel={ru ? "Ведомость деталей инструкции" : "Guide bill of materials"}>
        <Text style={styles.heading}>{ru ? "Ведомость деталей инструкции" : "Guide bill of materials"}</Text>
        {guide.bom.map((item) => (
          <Text style={styles.text} key={item.sourceNodeId}>
            {item.name} × {item.quantity}
            {item.visibleQuantity !== item.quantity
              ? ` · ${ru ? "видимо" : "visible"} ${item.visibleQuantity}`
              : ""}
          </Text>
        ))}
      </View>
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.text}>
          {ru ? "Выполнено" : "Completed"}: {completed.size}/{guide.steps.length}
          {saving ? (ru ? " · синхронизация…" : " · syncing…") : ""}
        </Text>
        {completed.size > 0 ? (
          <Pressable
            style={styles.chip}
            disabled={!editable || saving || !loaded}
            onPress={() => void save(new Set())}
          >
            <Text style={styles.chipText}>{ru ? "Сбросить" : "Reset"}</Text>
          </Pressable>
        ) : null}
      </View>
      {guide.steps.map((step, index) => (
        <View
          key={step.id}
          style={{ gap: 7, paddingTop: 12, borderTopWidth: index === 0 ? 0 : 1, borderTopColor: colors.border }}
        >
          <Pressable
            accessibilityRole="checkbox"
            accessibilityState={{ checked: completed.has(step.id) }}
            disabled={!editable || saving || !loaded}
            onPress={() => toggle(step.id)}
            style={[styles.row, { alignItems: "flex-start" }]}
          >
            <Text style={[styles.heading, { color: completed.has(step.id) ? colors.green : colors.text }]}>
              {completed.has(step.id) ? "✓" : "○"} {index + 1}. {ru ? step.titleRu : step.titleEn}
            </Text>
          </Pressable>
          <Text style={styles.text}>{ru ? step.detailRu : step.detailEn}</Text>
          <View
            style={{ flexDirection: "row", flexWrap: "wrap", gap: 7 }}
            accessibilityLabel={ru ? "Детали сцены" : "Scene parts"}
          >
            {step.nodeIds.map((nodeId) => (
              <Pressable
                key={nodeId}
                style={[styles.chip, { borderRadius: radii.pill }]}
                onPress={() => onSelectNode(nodeId)}
              >
                <Text style={styles.chipText}>{nodeNames.get(nodeId) ?? nodeId}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      ))}
      {syncError ? <Text style={[styles.muted, { color: colors.red }]}>{syncError}</Text> : null}
      <Text style={[styles.muted, { color: colors.yellow }]}>
        {ru
          ? editable
            ? "Отметки синхронизируются для этой версии между участниками workspace, но не подтверждают физическую сборку. Фотографии и внешний крепёж не добавлены; посадку и прочность проверьте физически."
            : "Отметки синхронизируются для этой версии; у вас доступ только для чтения. Они не подтверждают физическую сборку."
          : editable
            ? "Checks sync for this version across workspace members, but do not prove physical assembly. Photos and external fasteners are not included; validate fit and strength physically."
            : "Checks sync for this version; your access is read-only. They do not prove physical assembly."}
      </Text>
    </View>
  );
}
