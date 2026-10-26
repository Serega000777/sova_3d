import { useEffect, useState } from "react";
import { Pressable, Switch, Text, TextInput, View } from "react-native";

import {
  buildCadReconstructionProposal,
  buildFragmentRestorationProposal,
  FRAGMENT_RESTORATION_BOUNDARIES,
  type FragmentRestorationBoundary,
  type FragmentRestorationProposal,
} from "./fragment-restoration";
import { ModelViewer } from "./ModelViewer";
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
  mode,
  sourceModelUrl,
  sourceModelFormat,
  onApply,
  onClose,
}: {
  visible: boolean;
  language: "ru" | "en";
  sourceVersionId: string | null;
  busy: boolean;
  error: string | null;
  mode: "reconstruct" | "restore";
  sourceModelUrl: string | null;
  sourceModelFormat: "stl" | "glb";
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
    if (mode === "reconstruct") setBoundary(null);
  }, [mode, sourceVersionId, visible]);

  const edit = (change: () => void) => {
    change();
    setProposal(null);
    setValidationError(null);
  };

  const prepare = () => {
    if (!sourceVersionId) return;
    try {
      const build = mode === "restore"
        ? buildFragmentRestorationProposal
        : buildCadReconstructionProposal;
      setProposal(build({
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
      accessibilityLabel={mode === "restore"
        ? ru ? "Закрыть восстановление фрагмента" : "Close fragment restoration"
        : ru ? "Закрыть реконструкцию CAD" : "Close CAD reconstruction"}
    >
      <Text style={styles.heading}>
        {mode === "restore"
          ? ru ? "Восстановить симметричный фрагмент" : "Restore a symmetric fragment"
          : ru ? "Mesh → точная CAD-модель" : "Mesh → exact CAD model"}
      </Text>
      <Text style={styles.muted}>
        {mode === "restore"
          ? ru
            ? "Укажите плоскость, на которой заканчивается сохранившаяся половина. Предпросмотр ниже описывает точную CAD-операцию, но не угадывает форму произвольной трещины."
            : "Choose the plane where the surviving half ends. The preview describes an exact CAD operation; it does not guess an arbitrary fracture."
          : ru
            ? "Сервер распознает поддерживаемые призматические признаки сетки и перестроит их в редактируемую B-Rep-модель. Свободная форма и нераспознанные признаки не выдумываются."
            : "The server recognizes supported prismatic mesh features and rebuilds them as an editable B-Rep model. Freeform and unrecognized features are not invented."}
      </Text>

      <Text style={styles.text}>{ru ? "Граница симметрии" : "Symmetry boundary"}</Text>
      <View style={[styles.row, { flexWrap: "wrap" }]}>
        {mode === "reconstruct" ? (
          <Pressable
            accessibilityRole="button"
            style={[styles.button, boundary === null && styles.buttonPrimary]}
            disabled={busy}
            onPress={() => edit(() => setBoundary(null))}
          >
            <Text style={styles.buttonText}>{ru ? "Без достроения" : "No restoration"}</Text>
          </Pressable>
        ) : null}
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
            {proposal.body.restore_missing_half
              ? `${ru ? "Зеркально достроить половину от" : "Mirror the surviving half from"} ${BOUNDARY_LABEL[proposal.body.restore_missing_half]}`
              : ru ? "Перестроить распознанную сетку без зеркального достроения" : "Rebuild the recognized mesh without mirrored restoration"}
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
          {mode === "restore" && sourceModelUrl && proposal.body.restore_missing_half ? (
            <View style={{ gap: 6 }}>
              <ModelViewer
                url={sourceModelUrl}
                format={sourceModelFormat}
                bodyId="fragment-restoration-preview"
                selected={false}
                onSelect={() => undefined}
                height={220}
                showGrid={false}
                restorationPreview={proposal.body.restore_missing_half}
              />
              <Text style={styles.muted}>
                {ru
                  ? "Оранжевая сетка — зеркальная проверка выбранной границы на исходной модели. Это не серверный результат и не предсказанный контур скола."
                  : "The orange mesh checks the selected mirror boundary against the source model. It is not a server result or a predicted fracture contour."}
              </Text>
            </View>
          ) : null}
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
