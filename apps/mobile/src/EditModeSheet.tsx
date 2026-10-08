import type { ComponentKind, MeshEditReport } from "@physical-ai/contracts";
import { useEffect, useState } from "react";
import { Modal, Pressable, ScrollView, Text, TextInput, View } from "react-native";

import type { DirectMeshEditOperation } from "./ModelViewer";
import { colors, styles } from "./theme";

const KINDS: { kind: ComponentKind; label: string }[] = [
  { kind: "vertex", label: "Vertex" },
  { kind: "edge", label: "Edge" },
  { kind: "face", label: "Face" },
];

const OPERATIONS: {
  op: DirectMeshEditOperation;
  label: string;
  kinds: ComponentKind[];
}[] = [
  { op: "move", label: "Move", kinds: ["vertex", "edge", "face"] },
  { op: "extrude", label: "Extrude", kinds: ["face"] },
  { op: "inset", label: "Inset", kinds: ["face"] },
  { op: "bevel_edges", label: "Bevel", kinds: ["edge"] },
  { op: "delete_faces", label: "Delete", kinds: ["face"] },
];

function Stats({ report }: { report: MeshEditReport }) {
  const line = (label: string, value: MeshEditReport["before"]) =>
    value
      ? `${label}: ${value.vertices} vertices · ${value.faces} faces · ${
          value.volume_mm3 == null ? "volume —" : `${value.volume_mm3.toFixed(2)} mm³`
        } · ${value.watertight ? "watertight" : "open"}`
      : null;
  return (
    <View style={{ gap: 4 }}>
      {report.message ? (
        <Text style={report.ok ? styles.muted : styles.error}>{report.message}</Text>
      ) : null}
      {line("Before", report.before) ? <Text style={styles.muted}>{line("Before", report.before)}</Text> : null}
      {line("After", report.after) ? <Text style={styles.muted}>{line("After", report.after)}</Text> : null}
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

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={{ flex: 1, justifyContent: "flex-end" }} pointerEvents="box-none">
        <Pressable
          style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.18)" }}
          onPress={onClose}
          accessibilityLabel="Close mesh edit controls"
        />
        <View
          style={{
            maxHeight: "48%",
            backgroundColor: colors.panel,
            borderTopLeftRadius: 22,
            borderTopRightRadius: 22,
            borderColor: colors.border,
            borderWidth: 1,
            padding: 16,
            gap: 10,
          }}
        >
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <Text style={styles.heading}>Edit mesh</Text>
            <Pressable style={styles.chip} onPress={onOpenLayers}>
              <Text style={styles.chipText}>Layers</Text>
            </Pressable>
            <Pressable onPress={onClose} hitSlop={12} accessibilityLabel="Close">
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
                  {item.label}
                </Text>
              </Pressable>
            ))}
            <Pressable
              style={[styles.chip, multiSelect && { borderColor: colors.selection }]}
              onPress={() => onMultiSelectChange(!multiSelect)}
            >
              <Text style={[styles.chipText, multiSelect && { color: colors.selection }]}>
                Multi-select {multiSelect ? "on" : "off"}
              </Text>
            </Pressable>
          </View>

          <Text style={styles.muted}>
            {selectedCount > 0
              ? `${selectedCount} ${kind}${selectedCount === 1 ? "" : "s"} selected`
              : `Tap the model to select a ${kind}.`}
          </Text>

          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
            {choices.map((item) => (
              <Pressable
                key={item.op}
                style={[styles.button, operation === item.op && styles.buttonPrimary]}
                onPress={() => onOperationChange(item.op)}
              >
                <Text style={styles.buttonText}>{item.label}</Text>
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
                  accessibilityLabel="Mesh edit magnitude in millimetres"
                />
              ) : (
                <Pressable
                  style={[styles.chip, { borderColor: colors.selection }]}
                  onPress={() => setTyping(true)}
                >
                  <Text style={[styles.chipText, { color: colors.selection }]}>
                    {magnitude.toFixed(2)} mm · tap to type
                  </Text>
                </Pressable>
              )}
              <Text style={styles.muted}>Drag the selected component to scrub.</Text>
            </View>
          ) : null}

          {report ? <Stats report={report} /> : null}
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
                {busy ? "Applying…" : operation === "delete_faces" ? "Delete faces" : "Apply"}
              </Text>
            </Pressable>
            <Pressable style={styles.button} disabled={busy} onPress={onClose}>
              <Text style={styles.buttonText}>Cancel</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}
