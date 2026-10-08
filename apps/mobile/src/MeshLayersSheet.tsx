import type { MeshModifierStack, PhysicalAiClient } from "@physical-ai/contracts";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Switch, Text, View } from "react-native";

import { useIsTablet } from "./layout";
import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

type Entry = MeshModifierStack["modifiers"][number];

const LABELS: Record<string, { ru: string; en: string }> = {
  move: { ru: "Перемещение компонентов", en: "Move components" },
  extrude: { ru: "Выдавливание граней", en: "Extrude faces" },
  inset: { ru: "Отступ граней", en: "Inset faces" },
  delete_faces: { ru: "Удаление/заполнение", en: "Delete/fill faces" },
  bevel_edges: { ru: "Фаска рёбер", en: "Bevel edges" },
  detail: { ru: "Деталь поверхности", en: "Surface detail" },
};

export function MeshLayersSheet({
  visible,
  language,
  client,
  versionId,
  busy,
  onClose,
  onJob,
}: {
  visible: boolean;
  language: "ru" | "en";
  client: PhysicalAiClient | null;
  versionId: string | null;
  busy: boolean;
  onClose: () => void;
  onJob: (jobId: string) => Promise<void>;
}) {
  const ru = language === "ru";
  const isTablet = useIsTablet();
  const [stack, setStack] = useState<MeshModifierStack | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!visible || !client || !versionId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    void client
      .getMeshModifierStack(versionId)
      .then((value) => {
        if (cancelled) return;
        setStack(value);
        setEntries(value.modifiers);
        setDirty(false);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client, versionId, visible]);

  const move = (index: number, offset: -1 | 1) => {
    const destination = index + offset;
    if (destination < 0 || destination >= entries.length) return;
    setEntries((current) => {
      const next = [...current];
      [next[index], next[destination]] = [next[destination] as Entry, next[index] as Entry];
      return next;
    });
    setDirty(true);
  };

  const toggle = (id: string) => {
    setEntries((current) =>
      current.map((entry) =>
        entry.id === id ? { ...entry, enabled: !entry.enabled } : entry,
      ),
    );
    setDirty(true);
  };

  const apply = async () => {
    if (!client || !versionId || !stack) return;
    setLoading(true);
    setError(null);
    try {
      const accepted = await client.updateMeshModifierStack(versionId, {
        modifiers: entries.map(({ id, enabled }) => ({ id, enabled })),
        label: ru ? "Перестроить слои сетки" : "Rebuild mesh layers",
        scene_node_id: stack.scene_node_id,
      });
      await onJob(accepted.job_id);
      setDirty(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  };

  const disabled = busy || loading;
  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent={isTablet ? "72%" : "58%"}
      phoneBackdropColor="rgba(0,0,0,0.45)"
      accessibilityLabel={ru ? "Закрыть слои" : "Close layers"}
    >
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <Text style={styles.heading}>{ru ? "Слои" : "Layers"}</Text>
            <View style={styles.chip}>
              <Text style={styles.chipText}>{ru ? "Сетка" : "Mesh"}</Text>
            </View>
            <Pressable
              onPress={onClose}
              hitSlop={12}
              accessibilityLabel={ru ? "Закрыть" : "Close"}
            >
              <Text style={[styles.title, { color: colors.muted }]}>×</Text>
            </Pressable>
          </View>
          <Text style={styles.muted}>
            {ru
              ? "Шаги повторяются от исходной сетки в новой версии. Если после изменения порядка выделение устареет, исходная версия останется без изменений."
              : "Steps replay from the original mesh into a new version. If reordering makes a selection stale, the source version stays unchanged."}
          </Text>
          <ScrollView contentContainerStyle={{ gap: 8 }}>
            {entries.map((entry, index) => (
              <View
                key={entry.id}
                style={[
                  styles.card,
                  { backgroundColor: colors.panel2, opacity: entry.enabled ? 1 : 0.55 },
                ]}
              >
                <View style={[styles.row, { justifyContent: "space-between" }]}>
                  <Switch
                    value={entry.enabled}
                    disabled={disabled}
                    onValueChange={() => toggle(entry.id)}
                    trackColor={{ false: colors.border, true: colors.accent2 }}
                  />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.heading}>
                      {LABELS[entry.type]?.[language] ?? entry.type}
                    </Text>
                    <Text style={styles.mono}>
                      {entry.id} · {entry.tolerance_mm} {ru ? "мм" : "mm"}
                    </Text>
                  </View>
                  <Pressable
                    style={[styles.chip, (disabled || index === 0) && { opacity: 0.4 }]}
                    disabled={disabled || index === 0}
                    onPress={() => move(index, -1)}
                    accessibilityLabel={ru ? "Переместить вверх" : "Move up"}
                  >
                    <Text style={styles.chipText}>↑</Text>
                  </Pressable>
                  <Pressable
                    style={[
                      styles.chip,
                      (disabled || index === entries.length - 1) && { opacity: 0.4 },
                    ]}
                    disabled={disabled || index === entries.length - 1}
                    onPress={() => move(index, 1)}
                    accessibilityLabel={ru ? "Переместить вниз" : "Move down"}
                  >
                    <Text style={styles.chipText}>↓</Text>
                  </Pressable>
                </View>
              </View>
            ))}
            {!loading && entries.length === 0 ? (
              <Text style={styles.muted}>
                {ru
                  ? "В этой версии пока нет слоёв редактирования сетки."
                  : "This version has no mesh edit layers yet."}
              </Text>
            ) : null}
          </ScrollView>
          {loading ? (
            <Text style={styles.muted}>{ru ? "Загружаем слои…" : "Loading layers…"}</Text>
          ) : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <View style={styles.row}>
            <Pressable
              style={[
                styles.button,
                styles.buttonPrimary,
                (!dirty || disabled || !entries.some((entry) => entry.enabled)) && { opacity: 0.5 },
              ]}
              disabled={!dirty || disabled || !entries.some((entry) => entry.enabled)}
              onPress={() => void apply()}
            >
              <Text style={styles.buttonText}>{ru ? "Перестроить" : "Rebuild"}</Text>
            </Pressable>
            {dirty ? (
              <Pressable
                style={styles.button}
                disabled={disabled}
                onPress={() => {
                  setEntries(stack?.modifiers ?? []);
                  setDirty(false);
                }}
              >
                <Text style={styles.buttonText}>{ru ? "Сбросить" : "Reset"}</Text>
              </Pressable>
            ) : null}
          </View>
    </SheetShell>
  );
}
