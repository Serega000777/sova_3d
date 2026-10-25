import {
  ApiError,
  editableOperationParameters,
  operationParameterValue,
  setParameterOperation,
  type EditableOperationParameter,
  type OperationStack,
  type PhysicalAiClient,
} from "@physical-ai/contracts";
import { useEffect, useMemo, useState } from "react";
import { Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";

import { useIsTablet } from "./layout";
import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

type Entry = OperationStack["operations"][number];

const LABELS: Record<string, { ru: string; en: string }> = {
  create_box: { ru: "Коробка", en: "Box" },
  create_cylinder: { ru: "Цилиндр", en: "Cylinder" },
  create_sphere: { ru: "Сфера", en: "Sphere" },
  create_cone: { ru: "Конус", en: "Cone" },
  create_torus: { ru: "Тор", en: "Torus" },
  extrude: { ru: "Выдавливание", en: "Extrude" },
  loft: { ru: "Loft", en: "Loft" },
  sweep: { ru: "Sweep", en: "Sweep" },
  revolve: { ru: "Вращение", en: "Revolve" },
  nurbs_surface: { ru: "NURBS-поверхность", en: "NURBS surface" },
  analytic_surface_patch: { ru: "Аналитическая поверхность", en: "Analytic surface" },
  boolean: { ru: "Булева операция", en: "Boolean" },
  fillet: { ru: "Скругление", en: "Fillet" },
  chamfer: { ru: "Фаска", en: "Chamfer" },
  add_hole: { ru: "Отверстие", en: "Hole" },
  add_internal_thread: { ru: "Внутренняя резьба", en: "Internal thread" },
  add_hole_pattern: { ru: "Массив отверстий", en: "Hole pattern" },
  shell: { ru: "Оболочка", en: "Shell" },
  translate: { ru: "Перемещение", en: "Move" },
  rotate: { ru: "Поворот", en: "Rotate" },
  linear_pattern: { ru: "Линейный массив", en: "Linear pattern" },
  circular_pattern: { ru: "Круговой массив", en: "Circular pattern" },
  mirror: { ru: "Зеркало", en: "Mirror" },
  set_dimensions: { ru: "Габариты", en: "Dimensions" },
  set_parameter: { ru: "Параметр", en: "Parameter" },
};

export function CadHistorySheet({
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
  const [stack, setStack] = useState<OperationStack | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(false);
  const [absent, setAbsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [parameterInputs, setParameterInputs] = useState<Record<string, string>>({});
  const parameters = useMemo(() => editableOperationParameters(entries), [entries]);

  useEffect(() => {
    if (!visible || !client || !versionId) return;
    let cancelled = false;
    setLoading(true);
    setAbsent(false);
    setError(null);
    void client
      .getOperationStack(versionId)
      .then((value) => {
        if (cancelled) return;
        setStack(value);
        setEntries(value.operations);
        setDirty(false);
        const next: Record<string, string> = {};
        const editable = editableOperationParameters(value.operations);
        for (const [operationId, values] of Object.entries(editable)) {
          for (const parameter of values) next[`${operationId}:${parameter.parameter}`] = String(parameter.value);
        }
        setParameterInputs(next);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setStack(null);
        setEntries([]);
        if (reason instanceof ApiError && reason.status === 422) setAbsent(true);
        else setError(reason instanceof Error ? reason.message : String(reason));
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
      const accepted = await client.updateOperationStack(versionId, {
        operations: entries.map(({ id, enabled }) => ({ id, enabled })),
        label: ru ? "Пересобрать точную CAD-историю" : "Rebuild exact CAD history",
        preview: false,
      });
      await onJob(accepted.job_id);
      setDirty(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  };

  const editParameter = async (parameter: EditableOperationParameter, value: number) => {
    if (!client || !versionId) return;
    setLoading(true);
    setError(null);
    try {
      const accepted = await client.createEdit(versionId, {
        operations: [setParameterOperation(parameter, value)],
        label: ru
          ? `Изменить ${parameter.parameter} операции ${parameter.operationId}`
          : `Edit ${parameter.parameter} on ${parameter.operationId}`,
        preview: false,
      });
      await onJob(accepted.job_id);
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
      maxHeightPercent={isTablet ? "76%" : "66%"}
      phoneBackdropColor="rgba(0,0,0,0.45)"
      accessibilityLabel={ru ? "Закрыть историю точного CAD" : "Close exact CAD history"}
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.heading}>{ru ? "История точного CAD" : "Exact CAD history"}</Text>
        <View style={styles.chip}>
          <Text style={styles.chipText}>B-Rep</Text>
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
          ? "Порядок и выключенные шаги сохраняются в новой immutable-версии. Зависимую операцию нельзя поставить раньше её тела."
          : "Order and disabled steps are saved in a new immutable version. A dependent feature cannot precede its body."}
      </Text>
      <ScrollView contentContainerStyle={{ gap: 8 }}>
        {entries.map((entry, index) => {
          const editable = parameters[entry.id] ?? [];
          return (
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
              <View style={{ flex: 1, gap: 3 }}>
                <Text style={styles.heading}>{LABELS[entry.type]?.[language] ?? entry.type}</Text>
                <Text style={styles.mono}>{entry.id}</Text>
                {entry.dependencies.length > 0 ? (
                  <Text style={styles.muted}>
                    {ru ? "зависит от" : "depends on"} {entry.dependencies.join(", ")}
                  </Text>
                ) : null}
              </View>
              <Pressable
                style={[styles.chip, (disabled || index === 0) && { opacity: 0.4 }]}
                disabled={disabled || index === 0}
                onPress={() => move(index, -1)}
                accessibilityLabel={ru ? "Переместить выше" : "Move up"}
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
                accessibilityLabel={ru ? "Переместить ниже" : "Move down"}
              >
                <Text style={styles.chipText}>↓</Text>
              </Pressable>
            </View>
            {editable.map((parameter) => {
              const key = `${entry.id}:${parameter.parameter}`;
              const input = parameterInputs[key] ?? String(parameter.value);
              const parsed = operationParameterValue(parameter, input);
              return (
                <View key={parameter.parameter} style={{ gap: 4 }}>
                  <Text style={styles.muted}>{parameter.parameter.replaceAll("_", " ")}</Text>
                  <View style={styles.row}>
                    <TextInput
                      style={[styles.input, { flex: 1 }]}
                      keyboardType="numbers-and-punctuation"
                      value={input}
                      editable={!disabled && entry.enabled}
                      onChangeText={(value) => setParameterInputs((current) => ({ ...current, [key]: value }))}
                      accessibilityLabel={`${LABELS[entry.type]?.[language] ?? entry.type}: ${parameter.parameter}`}
                    />
                    <Text style={styles.muted}>{parameter.unit === "deg" ? "°" : "mm"}</Text>
                    <Pressable
                      style={[
                        styles.chip,
                        (disabled || !entry.enabled || parsed === null || parsed === parameter.value) && { opacity: 0.4 },
                      ]}
                      disabled={disabled || !entry.enabled || parsed === null || parsed === parameter.value}
                      onPress={() => parsed !== null && void editParameter(parameter, parsed)}
                    >
                      <Text style={styles.chipText}>{ru ? "Применить" : "Apply"}</Text>
                    </Pressable>
                  </View>
                </View>
              );
            })}
          </View>
          );
        })}
        {absent ? (
          <Text style={styles.muted}>
            {ru
              ? "У этой imported/scanned версии ещё нет точной CAD-истории. Создайте её через Mesh → точный CAD."
              : "This imported/scanned version has no exact CAD history yet. Create one through Mesh → exact CAD."}
          </Text>
        ) : null}
      </ScrollView>
      {loading ? <Text style={styles.muted}>{ru ? "Загружаем историю…" : "Loading history…"}</Text> : null}
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
          <Text style={styles.buttonText}>{ru ? "Пересобрать" : "Rebuild"}</Text>
        </Pressable>
        {dirty ? (
          <Pressable
            style={styles.button}
            disabled={disabled}
            onPress={() => {
              setEntries(stack?.operations ?? []);
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
