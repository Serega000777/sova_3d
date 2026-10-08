import type { ComponentKind, MeshEditReport } from "@physical-ai/contracts";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import type { DirectMeshEditOperation } from "./ModelViewer";
import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

type Language = "ru" | "en";

const KINDS: {
  kind: ComponentKind;
  label: Record<Language, string>;
  selectLabel: Record<Language, string>;
}[] = [
  {
    kind: "vertex",
    label: { ru: "Вершина", en: "Vertex" },
    selectLabel: { ru: "вершину", en: "a vertex" },
  },
  {
    kind: "edge",
    label: { ru: "Ребро", en: "Edge" },
    selectLabel: { ru: "ребро", en: "an edge" },
  },
  {
    kind: "face",
    label: { ru: "Грань", en: "Face" },
    selectLabel: { ru: "грань", en: "a face" },
  },
];

const OPERATIONS: {
  op: DirectMeshEditOperation;
  label: Record<Language, string>;
  kinds: ComponentKind[];
}[] = [
  {
    op: "move",
    label: { ru: "Переместить", en: "Move" },
    kinds: ["vertex", "edge", "face"],
  },
  { op: "extrude", label: { ru: "Выдавить", en: "Extrude" }, kinds: ["face"] },
  { op: "inset", label: { ru: "Отступ", en: "Inset" }, kinds: ["face"] },
  { op: "bevel_edges", label: { ru: "Фаска", en: "Bevel" }, kinds: ["edge"] },
  { op: "delete_faces", label: { ru: "Удалить", en: "Delete" }, kinds: ["face"] },
];

function Stats({ report, language }: { report: MeshEditReport; language: Language }) {
  const ru = language === "ru";
  const line = (label: string, value: MeshEditReport["before"]) => {
    if (!value) return null;
    if (ru) {
      return `${label}: вершин ${value.vertices} · граней ${value.faces} · ${
        value.volume_mm3 == null ? "объём —" : `объём ${value.volume_mm3.toFixed(2)} мм³`
      } · ${value.watertight ? "замкнута" : "открыта"}`;
    }
    return `${label}: ${value.vertices} vertices · ${value.faces} faces · ${
      value.volume_mm3 == null ? "volume —" : `${value.volume_mm3.toFixed(2)} mm³`
    } · ${value.watertight ? "watertight" : "open"}`;
  };
  return (
    <View style={{ gap: 4 }}>
      {report.message ? (
        <Text style={report.ok ? styles.muted : styles.error}>{report.message}</Text>
      ) : null}
      {line(ru ? "До" : "Before", report.before) ? (
        <Text style={styles.muted}>{line(ru ? "До" : "Before", report.before)}</Text>
      ) : null}
      {line(ru ? "После" : "After", report.after) ? (
        <Text style={styles.muted}>{line(ru ? "После" : "After", report.after)}</Text>
      ) : null}
      {report.warnings.map((warning) => (
        <Text key={warning} style={[styles.muted, { color: colors.yellow }]}>
          {warning}
        </Text>
      ))}
    </View>
  );
}

export function EditModeSheet({
  visible,
  language,
  kind,
  multiSelect,
  selectedCount,
  operation,
  magnitude,
  busy,
  report,
  error,
  onClose,
  onKindChange,
  onMultiSelectChange,
  onOperationChange,
  onMagnitudeChange,
  onApply,
  onOpenLayers,
}: {
  visible: boolean;
  language: Language;
  kind: ComponentKind;
  multiSelect: boolean;
  selectedCount: number;
  operation: DirectMeshEditOperation | null;
  magnitude: number;
  busy: boolean;
  report: MeshEditReport | null;
  error: string | null;
  onClose: () => void;
  onKindChange: (kind: ComponentKind) => void;
  onMultiSelectChange: (enabled: boolean) => void;
  onOperationChange: (operation: DirectMeshEditOperation) => void;
  onMagnitudeChange: (value: number) => void;
  onApply: () => void;
  onOpenLayers: () => void;
}) {
  const ru = language === "ru";
  const [typing, setTyping] = useState(false);
  const [draft, setDraft] = useState(magnitude.toString());

  useEffect(() => {
    if (!typing) setDraft(magnitude.toString());
  }, [magnitude, typing]);

  const commitDraft = () => {
    const value = Number(draft.replace(",", "."));
    if (Number.isFinite(value)) onMagnitudeChange(value);
    setTyping(false);
  };
  const choices = OPERATIONS.filter((item) => item.kinds.includes(kind));
  const selectedKind = KINDS.find((item) => item.kind === kind);

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="48%"
      accessibilityLabel={ru ? "Закрыть инструменты редактирования сетки" : "Close mesh edit controls"}
    >
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <Text style={styles.heading}>{ru ? "Редактирование сетки" : "Edit mesh"}</Text>
            <Pressable style={styles.chip} onPress={onOpenLayers}>
              <Text style={styles.chipText}>{ru ? "Слои" : "Layers"}</Text>
            </Pressable>
            <Pressable
              onPress={onClose}
              hitSlop={12}
              accessibilityLabel={ru ? "Закрыть" : "Close"}
            >
              <Text style={[styles.title, { color: colors.muted }]}>×</Text>
            </Pressable>
          </View>

          <View style={styles.row}>
            {KINDS.map((item) => (
              <Pressable
                key={item.kind}
                style={[styles.chip, item.kind === kind && { borderColor: colors.accent }]}
                onPress={() => onKindChange(item.kind)}
              >
                <Text style={[styles.chipText, item.kind === kind && { color: colors.accent }]}>
                  {item.label[language]}
                </Text>
              </Pressable>
            ))}
            <Pressable
              style={[styles.chip, multiSelect && { borderColor: colors.selection }]}
              onPress={() => onMultiSelectChange(!multiSelect)}
            >
              <Text style={[styles.chipText, multiSelect && { color: colors.selection }]}>
                {ru ? "Множественный выбор" : "Multi-select"}{" "}
                {multiSelect ? (ru ? "вкл." : "on") : ru ? "выкл." : "off"}
              </Text>
            </Pressable>
          </View>

          <Text style={styles.muted}>
            {selectedCount > 0
              ? ru
                ? `Выбрано элементов: ${selectedCount}`
                : `${selectedCount} ${kind}${selectedCount === 1 ? "" : "s"} selected`
              : ru
                ? `Коснитесь модели, чтобы выбрать ${selectedKind?.selectLabel.ru ?? "элемент"}.`
                : `Tap the model to select ${selectedKind?.selectLabel.en ?? "a component"}.`}
          </Text>

          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
            {choices.map((item) => (
              <Pressable
                key={item.op}
                style={[styles.button, operation === item.op && styles.buttonPrimary]}
                onPress={() => onOperationChange(item.op)}
              >
                <Text style={styles.buttonText}>{item.label[language]}</Text>
              </Pressable>
            ))}
          </ScrollView>

          {operation && operation !== "delete_faces" ? (
            <View style={styles.row}>
              {typing ? (
                <TextInput
                  autoFocus
                  style={[styles.input, { width: 130 }]}
                  value={draft}
                  onChangeText={setDraft}
                  keyboardType="decimal-pad"
                  onBlur={commitDraft}
                  onSubmitEditing={commitDraft}
                  accessibilityLabel={
                    ru
                      ? "Величина правки сетки в миллиметрах"
                      : "Mesh edit magnitude in millimetres"
                  }
                />
              ) : (
                <Pressable
                  style={[styles.chip, { borderColor: colors.selection }]}
                  onPress={() => setTyping(true)}
                >
                  <Text style={[styles.chipText, { color: colors.selection }]}>
                    {magnitude.toFixed(2)} {ru ? "мм · нажмите, чтобы ввести" : "mm · tap to type"}
                  </Text>
                </Pressable>
              )}
              <Text style={styles.muted}>
                {ru
                  ? "Перетащите выбранный элемент, чтобы изменить величину."
                  : "Drag the selected component to scrub."}
              </Text>
            </View>
          ) : null}

          {report ? <Stats report={report} language={language} /> : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}

          <View style={styles.row}>
            <Pressable
              style={[
                styles.button,
                styles.buttonPrimary,
                (!operation || selectedCount === 0 || busy) && { opacity: 0.5 },
              ]}
              disabled={!operation || selectedCount === 0 || busy}
              onPress={onApply}
            >
              <Text style={styles.buttonText}>
                {busy
                  ? ru
                    ? "Применяем…"
                    : "Applying…"
                  : operation === "delete_faces"
                    ? ru
                      ? "Удалить грани"
                      : "Delete faces"
                    : ru
                      ? "Применить"
                      : "Apply"}
              </Text>
            </Pressable>
            <Pressable style={styles.button} disabled={busy} onPress={onClose}>
              <Text style={styles.buttonText}>{ru ? "Отмена" : "Cancel"}</Text>
            </Pressable>
          </View>
    </SheetShell>
  );
}
