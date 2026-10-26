import AsyncStorage from "@react-native-async-storage/async-storage";
import { useEffect, useMemo, useState } from "react";
import { Pressable, Text, View } from "react-native";

import type { MechanismAssemblyGuide } from "./mechanism-assembly-guide";
import { colors, radii, styles } from "./theme";

export function AssemblyGuideCard({
  guide,
  versionId,
  language,
  nodeNames,
  onSelectNode,
}: {
  guide: MechanismAssemblyGuide;
  versionId: string;
  language: "ru" | "en";
  nodeNames: ReadonlyMap<string, string>;
  onSelectNode: (nodeId: string) => void;
}) {
  const ru = language === "ru";
  const storageKey = `sova:assembly-guide:v1:${versionId}:${guide.kind}`;
  const stepIds = useMemo(() => new Set(guide.steps.map((step) => step.id)), [guide.steps]);
  const [completed, setCompleted] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    setCompleted(new Set());
    void AsyncStorage.getItem(storageKey)
      .then((raw) => {
        if (cancelled || raw === null) return;
        const parsed: unknown = JSON.parse(raw);
        if (!Array.isArray(parsed)) return;
        setCompleted(new Set(parsed.filter((value): value is string => typeof value === "string" && stepIds.has(value))));
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [stepIds, storageKey]);

  const toggle = (stepId: string) => {
    setCompleted((current) => {
      const next = new Set(current);
      if (next.has(stepId)) next.delete(stepId);
      else next.add(stepId);
      void AsyncStorage.setItem(storageKey, JSON.stringify([...next])).catch(() => undefined);
      return next;
    });
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
          ? "Шаги построены только по сохранённым деталям механизма. Нажмите деталь, чтобы выделить её в сцене."
          : "Steps use only the mechanism parts saved in this version. Press a part to select it in the scene."}
      </Text>
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.text}>{ru ? "Выполнено" : "Completed"}: {completed.size}/{guide.steps.length}</Text>
        {completed.size > 0 ? (
          <Pressable
            style={styles.chip}
            onPress={() => {
              setCompleted(new Set());
              void AsyncStorage.removeItem(storageKey).catch(() => undefined);
            }}
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
      <Text style={[styles.muted, { color: colors.yellow }]}>
        {ru
          ? "Отметки хранятся только на этом устройстве для этой версии и не подтверждают физическую сборку. Фотографии и внешний крепёж не добавлены; посадку и прочность проверьте физически."
          : "Checks stay only on this device for this version and do not prove physical assembly. Photos and external fasteners are not included; validate fit and strength physically."}
      </Text>
    </View>
  );
}
