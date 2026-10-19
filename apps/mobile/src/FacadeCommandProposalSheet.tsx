import type { FacadeCommandProposal } from "@physical-ai/contracts";
import { Pressable, Text, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

export function FacadeCommandProposalSheet({
  visible,
  language,
  proposal,
  busy,
  error,
  onApply,
  onClose,
}: {
  visible: boolean;
  language: "ru" | "en";
  proposal: FacadeCommandProposal | null;
  busy: boolean;
  error: string | null;
  onApply: () => void;
  onClose: () => void;
}) {
  const ru = language === "ru";
  if (!proposal) return null;
  const close = () => {
    if (!busy) onClose();
  };

  return (
    <SheetShell
      visible={visible}
      onClose={close}
      maxHeightPercent="62%"
      tabletWidth={520}
      accessibilityLabel={
        ru ? "Закрыть предложение изменения фасада" : "Close facade change proposal"
      }
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.heading}>{ru ? "Предложенное изменение" : "Proposed change"}</Text>
        <View style={[styles.chip, { borderColor: colors.yellow }]}>
          <Text style={[styles.chipText, { color: colors.yellow }]}>
            {ru ? "Точный фасад" : "Exact facade"}
          </Text>
        </View>
        <Pressable
          onPress={close}
          disabled={busy}
          hitSlop={12}
          accessibilityLabel={ru ? "Закрыть" : "Close"}
        >
          <Text style={[styles.title, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>

      <Text style={styles.text}>{ru ? proposal.label_ru : proposal.label_en}</Text>
      <View style={[styles.row, { flexWrap: "wrap" }]}>
        <View style={styles.chip}>
          <Text style={styles.chipText}>
            {ru ? "Текущее" : "Current"}: {proposal.current_value_mm} {proposal.unit}
          </Text>
        </View>
        <Text style={[styles.text, { color: colors.muted }]}>→</Text>
        <View style={[styles.chip, { borderColor: colors.accent }]}>
          <Text style={[styles.chipText, { color: colors.accent }]}>
            {ru ? "Новое" : "New"}: {proposal.new_value_mm} {proposal.unit}
          </Text>
        </View>
      </View>
      <Text style={styles.muted}>
        {ru
          ? "Задача ещё не запущена. Проверьте параметр перед построением новой версии."
          : "No job has started yet. Check the parameter before building a new version."}
      </Text>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <View style={styles.row}>
        <Pressable
          style={[styles.button, styles.buttonPrimary, busy && { opacity: 0.45 }]}
          disabled={busy}
          onPress={onApply}
        >
          <Text style={styles.buttonText}>
            {busy
              ? ru ? "Применяем…" : "Applying…"
              : ru ? "Применить как новую версию" : "Apply as a new version"}
          </Text>
        </Pressable>
        <Pressable style={styles.button} disabled={busy} onPress={close}>
          <Text style={styles.buttonText}>{ru ? "Отмена" : "Cancel"}</Text>
        </Pressable>
      </View>
    </SheetShell>
  );
}
