/** Reference 67: canonical scene BOM and a reversible exploded inspection preview. */
import type { AssemblyInspection, PhysicalAiClient } from "@physical-ai/contracts";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

export type ExplodedPreview = { order: string[]; gapMm: number };

const GAPS = [10, 30, 60] as const;

export function AssemblyInspectionSheet({
  visible,
  language,
  client,
  versionId,
  selectedNodeId,
  onClose,
  onSelectNode,
  onPreviewChange,
}: {
  visible: boolean;
  language: "ru" | "en";
  client: PhysicalAiClient | null;
  versionId: string | null;
  selectedNodeId: string | null;
  onClose: () => void;
  onSelectNode: (nodeId: string) => void;
  onPreviewChange: (preview: ExplodedPreview | null) => void;
}) {
  const ru = language === "ru";
  const [inspection, setInspection] = useState<AssemblyInspection | null>(null);
  const [gapMm, setGapMm] = useState<(typeof GAPS)[number]>(30);
  const [exploded, setExploded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!visible || !client || !versionId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setInspection(null);
    setExploded(false);
    onPreviewChange(null);
    void client.inspectAssembly(versionId)
      .then((value) => {
        if (!cancelled) setInspection(value);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [client, onPreviewChange, versionId, visible]);

  const setPreview = (nextExploded: boolean, nextGap = gapMm) => {
    setExploded(nextExploded);
    setGapMm(nextGap);
    onPreviewChange(
      nextExploded && inspection
        ? { order: inspection.exploded_order, gapMm: nextGap }
        : null,
    );
  };

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="92%"
      tabletWidth={680}
      accessibilityLabel={ru ? "Закрыть состав сборки" : "Close assembly manifest"}
      contentGap={12}
    >
      <View style={[styles.row, { justifyContent: "space-between", alignItems: "flex-start" }]}>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.title}>{ru ? "Сборка деталей" : "Parts assembly"}</Text>
          <Text style={styles.sectionSubtitle}>
            {ru
              ? "Состав и порядок читаются из неизменяемой scene graph; экземпляры считаются по их исходному узлу."
              : "Composition and order come from the immutable scene graph; instances are counted against their source node."}
          </Text>
        </View>
        <Pressable onPress={onClose} hitSlop={12} accessibilityLabel={ru ? "Закрыть" : "Close"}>
          <Text style={[styles.title, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>

      {loading ? <Text style={styles.muted}>{ru ? "Проверяем структуру…" : "Validating structure…"}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {inspection ? (
        <ScrollView contentContainerStyle={{ gap: 12 }} showsVerticalScrollIndicator={false}>
          <View style={[styles.card, { gap: 5, backgroundColor: colors.panel2 }]}>
            <Text style={[styles.heading, { color: colors.green }]}>✓ {ru ? "Структура проверена" : "Structure validated"}</Text>
            <Text style={styles.muted}>
              {inspection.component_count} {ru ? "компонентов" : "components"} · {inspection.visible_component_count} {ru ? "видимых" : "visible"} · {inspection.unique_geometry_count} {ru ? "уникальных геометрий" : "unique geometries"}
            </Text>
            <Text style={[styles.muted, { color: colors.yellow }]}>
              {ru
                ? "Связи mate/joint и столкновения всей сцены не проверяются."
                : "Mate/joint constraints and whole-scene collisions are not checked."}
            </Text>
          </View>

          <View style={{ gap: 8 }}>
            <Text style={styles.heading}>{ru ? "Ведомость деталей" : "Bill of materials"}</Text>
            {inspection.bom.map((item, index) => (
              <View key={item.source_node_id} style={[styles.card, { gap: 4, backgroundColor: colors.panel2 }]}>
                <View style={[styles.row, { justifyContent: "space-between" }]}>
                  <Text style={styles.text}>{index + 1}. {item.name}</Text>
                  <Text style={styles.chipText}>×{item.quantity}</Text>
                </View>
                <Text style={styles.muted}>{item.node_ids.join(" · ")}</Text>
              </View>
            ))}
          </View>

          <View style={{ gap: 8 }}>
            <Text style={styles.heading}>{ru ? "Порядок разнесения" : "Exploded order"}</Text>
            {inspection.components.map((component) => (
              <Pressable
                key={component.node_id}
                disabled={!component.effective_visible}
                onPress={() => onSelectNode(component.node_id)}
                style={[
                  styles.button,
                  selectedNodeId === component.node_id && { borderColor: colors.selection },
                  !component.effective_visible && { opacity: 0.45 },
                ]}
              >
                <Text style={styles.buttonText}>
                  {component.order}. {component.name}{component.instance_of ? ` · ${ru ? "экземпляр" : "instance"}` : ""}
                </Text>
              </Pressable>
            ))}
            <Text style={styles.muted}>
              {ru
                ? "Preview следует сохранённому порядку узлов и не выдаётся за инструкцию монтажа."
                : "The preview follows stored node order and is not presented as an assembly procedure."}
            </Text>
          </View>

          <View style={{ gap: 8 }}>
            <Text style={styles.heading}>{ru ? "Шаг по глобальной Z" : "Global Z spacing"}</Text>
            <View style={[styles.row, { flexWrap: "wrap" }]}>
              {GAPS.map((value) => (
                <Pressable
                  key={value}
                  onPress={() => setPreview(exploded, value)}
                  style={[styles.chip, gapMm === value && { borderColor: colors.selection }]}
                >
                  <Text style={styles.chipText}>{value} {ru ? "мм" : "mm"}</Text>
                </Pressable>
              ))}
            </View>
            <Pressable
              style={[styles.button, styles.buttonPrimary]}
              disabled={inspection.exploded_order.length < 2}
              onPress={() => setPreview(!exploded)}
            >
              <Text style={styles.buttonText}>
                {exploded ? (ru ? "Собрать preview" : "Collapse preview") : (ru ? "Разнести детали" : "Explode parts")}
              </Text>
            </Pressable>
          </View>
        </ScrollView>
      ) : null}
    </SheetShell>
  );
}
