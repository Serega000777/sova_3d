import { useEffect, useState } from "react";
import { Pressable, Switch, Text, TextInput, View } from "react-native";

import {
  buildFragmentRestorationProposal,
  FRAGMENT_RESTORATION_BOUNDARIES,
  type FragmentRestorationBoundary,
  type FragmentRestorationProposal,
} from "./fragment-restoration";
import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

const BOUNDARY_LABEL: Record<FragmentRestorationBoundary, string> = {
  x_min: "X−",
  x_max: "X+",
  y_min: "Y−",
  y_max: "Y+",
  z_min: "Z−",
  z_max: "Z+",
};

export function FragmentRestorationSheet({
  visible,
  language,
  sourceVersionId,
  busy,
  error,
  onApply,
  onClose,
}: {
  visible: boolean;
  language: "ru" | "en";
  sourceVersionId: string | null;
  busy: boolean;
  error: string | null;
  onApply: (proposal: FragmentRestorationProposal) => void;
  onClose: () => void;
}) {
  const ru = language === "ru";
  const [tolerance, setTolerance] = useState("0.2");
  const [boundary, setBoundary] = useState<FragmentRestorationBoundary | null>(null);
  const [reinforce, setReinforce] = useState(false);
  const [reinforcementPercent, setReinforcementPercent] = useState("20");
  const [proposal, setProposal] = useState<FragmentRestorationProposal | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    setProposal(null);
    setValidationError(null);
  }, [sourceVersionId]);

  const edit = (change: () => void) => {
    change();
    setProposal(null);
    setValidationError(null);
  };

  const prepare = () => {
    if (!sourceVersionId) return;
    try {
      setProposal(buildFragmentRestorationProposal({
        sourceVersionId,
        tolerance,
        boundary,
        reinforce,
        reinforcementPercent,
      }));
      setValidationError(null);
    } catch (reason) {
      setProposal(null);
      setValidationError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <SheetShell
      visible={visible}
      onClose={() => !busy && onClose()}
      maxHeightPercent="88%"
      tabletWidth={560}
      accessibilityLabel={ru ? "Закрыть восстановление фрагмента" : "Close fragment restoration"}
    >
      <Text style={styles.heading}>{ru ? "Восстановить симметричный фрагмент" : "Restore a symmetric fragment"}</Text>
      <Text style={styles.muted}>
        {ru
          ? "Укажите плоскость, на которой заканчивается сохранившаяся половина. Предпросмотр ниже описывает точную CAD-операцию, но не угадывает форму произвольной трещины."
          : "Choose the plane where the surviving half ends. The preview describes an exact CAD operation; it does not guess an arbitrary fracture."}
      </Text>

      <Text style={styles.text}>{ru ? "Граница симметрии" : "Symmetry boundary"}</Text>
      <View style={[styles.row, { flexWrap: "wrap" }]}>
        {FRAGMENT_RESTORATION_BOUNDARIES.map((value) => (
          <Pressable
            key={value}
            accessibilityRole="button"
            style={[styles.button, boundary === value && styles.buttonPrimary]}
            disabled={busy}
            onPress={() => edit(() => setBoundary(value))}
          >
            <Text style={styles.buttonText}>{BOUNDARY_LABEL[value]}</Text>
          </Pressable>
        ))}
      </View>

      <Text style={styles.text}>{ru ? "Допуск распознавания, мм" : "Recognition tolerance, mm"}</Text>
      <TextInput
        style={styles.input}
        keyboardType="decimal-pad"
        value={tolerance}
        editable={!busy}
        onChangeText={(value) => edit(() => setTolerance(value))}
      />

      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.text}>{ru ? "Усилить толщину" : "Reinforce thickness"}</Text>
          <Text style={styles.muted}>
            {ru
              ? "Только для одной призматической детали без боковых отверстий; это не расчёт прочности."
              : "Only for one prismatic part without side holes; this is not a strength calculation."}
          </Text>
        </View>
        <Switch
          value={reinforce}
          disabled={busy}
          onValueChange={(value) => edit(() => setReinforce(value))}
        />
      </View>
      {reinforce ? (
        <TextInput
          accessibilityLabel={ru ? "Увеличение толщины в процентах" : "Thickness increase percent"}
          style={styles.input}
          keyboardType="decimal-pad"
          value={reinforcementPercent}
          editable={!busy}
          onChangeText={(value) => edit(() => setReinforcementPercent(value))}
        />
      ) : null}

      {proposal ? (
        <View style={[styles.card, { gap: 7, borderColor: colors.yellow }]} accessibilityLabel={ru ? "Предварительный план восстановления" : "Fragment restoration preview"}>
          <Text style={styles.heading}>{ru ? "План готов — задача ещё не запущена" : "Plan ready — no job started"}</Text>
          <Text style={styles.text}>
            {ru ? "Зеркально достроить половину от" : "Mirror the surviving half from"} {BOUNDARY_LABEL[proposal.body.restore_missing_half]}
          </Text>
          <Text style={styles.muted}>
            {ru ? "Допуск" : "Tolerance"}: {proposal.body.tolerance_mm} {ru ? "мм" : "mm"}
            {proposal.body.reinforce_thickness_percent !== null
              ? ` · ${ru ? "усиление" : "reinforcement"} ${proposal.body.reinforce_thickness_percent}%`
              : ""}
          </Text>
          <Text style={styles.muted}>
            {ru
              ? "После подтверждения сервер распознает поддерживаемые призматические признаки, выполнит fused mirror в CAD-ядре и измерит отклонение от исходной сетки."
              : "After confirmation, the server recognizes supported prismatic features, runs a fused mirror in the CAD kernel, and measures deviation from the source mesh."}
          </Text>
        </View>
      ) : null}

      {validationError || error ? <Text style={styles.error}>{validationError ?? error}</Text> : null}
      <View style={styles.row}>
        {proposal ? (
          <Pressable
            style={[styles.button, styles.buttonPrimary, busy && { opacity: 0.45 }]}
            disabled={busy}
            onPress={() => onApply(proposal)}
          >
            <Text style={styles.buttonText}>{ru ? "Применить как новую версию" : "Apply as a new version"}</Text>
          </Pressable>
        ) : (
          <Pressable style={[styles.button, styles.buttonPrimary]} disabled={busy || !sourceVersionId} onPress={prepare}>
            <Text style={styles.buttonText}>{ru ? "Подготовить план" : "Prepare plan"}</Text>
          </Pressable>
        )}
        <Pressable style={styles.button} disabled={busy} onPress={onClose}>
          <Text style={styles.buttonText}>{ru ? "Отмена" : "Cancel"}</Text>
        </Pressable>
      </View>
    </SheetShell>
  );
}
