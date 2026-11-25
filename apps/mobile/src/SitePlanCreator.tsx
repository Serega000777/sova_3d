import {
  type PhysicalAiClient,
  type SitePlan,
  type Version,
} from "@physical-ai/contracts";
import { useEffect, useRef, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import {
  SITE_SIDES,
  sitePlanProblem,
  verifiedSitePlanJobVersionId,
  verifiedSitePlanVersion,
  type HouseFootprintDimensions,
  type SiteSide,
} from "./site-plan-creator";
import { colors, styles } from "./theme";

const SIDE_LABELS: Record<SiteSide, string> = {
  north: "Север",
  east: "Восток",
  south: "Юг",
  west: "Запад",
};

type EditableSitePlan = SitePlan & {
  corner_elevations_mm: number[];
  fence_sides: SiteSide[];
  minimum_boundary_clearance_mm: number;
};

function clonePlan(value: SitePlan): EditableSitePlan {
  return {
    ...value,
    corner_elevations_mm: [...(value.corner_elevations_mm ?? [0, 0, 0, 0])],
    path_points_mm: value.path_points_mm.map((point) => [...point]),
    fence_sides: [...(value.fence_sides ?? SITE_SIDES)],
    minimum_boundary_clearance_mm: value.minimum_boundary_clearance_mm ?? 500,
    boundary_rule_set: value.boundary_rule_set ? {
      ...value.boundary_rule_set,
      required_clearances_mm: { ...value.boundary_rule_set.required_clearances_mm },
    } : null,
  };
}

function NumberField({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  const [text, setText] = useState(String(value));
  return (
    <View style={{ flex: 1, minWidth: 128, gap: 4 }}>
      <Text style={styles.sectionSubtitle}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        editable={!disabled}
        keyboardType="numbers-and-punctuation"
        onChangeText={(next) => {
          setText(next);
          onChange(next.trim() === "" ? Number.NaN : Number(next.replace(",", ".")));
        }}
        selectTextOnFocus
        style={styles.input}
        value={text}
      />
    </View>
  );
}

export function SitePlanCreator({
  client,
  projectId,
  sourceVersionId,
  initialPlan,
  houseDimensions,
  onApplied,
}: {
  client: PhysicalAiClient;
  projectId: string;
  sourceVersionId: string;
  initialPlan: SitePlan;
  houseDimensions: HouseFootprintDimensions;
  onApplied: (version: Version) => void;
}) {
  const [plan, setPlan] = useState<EditableSitePlan>(() => clonePlan(initialPlan));
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  function update<K extends keyof EditableSitePlan>(key: K, value: EditableSitePlan[K]) {
    setPlan((current) => ({ ...current, [key]: value }));
    setError(null);
  }

  function toggleFence(side: SiteSide) {
    const current = plan.fence_sides;
    update(
      "fence_sides",
      current.includes(side) ? current.filter((item) => item !== side) : [...current, side],
    );
  }

  function setRulesEnabled(enabled: boolean) {
    update("boundary_rule_set", enabled ? {
      schema_version: 1,
      authority_status: "owner_declared",
      jurisdiction: "",
      title: "",
      source_url: "https://",
      source_version: "",
      effective_date: new Date().toISOString().slice(0, 10),
      required_clearances_mm: {
        north: plan.minimum_boundary_clearance_mm ?? 500,
        east: plan.minimum_boundary_clearance_mm ?? 500,
        south: plan.minimum_boundary_clearance_mm ?? 500,
        west: plan.minimum_boundary_clearance_mm ?? 500,
      },
    } : null);
  }

  async function compose() {
    if (inFlight.current) return;
    const problem = sitePlanProblem(plan, houseDimensions);
    if (problem) {
      setError(problem);
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setError(null);
    const expected = clonePlan({
      ...plan,
      boundary_rule_set: plan.boundary_rule_set ? {
        ...plan.boundary_rule_set,
        jurisdiction: plan.boundary_rule_set.jurisdiction.trim(),
        title: plan.boundary_rule_set.title.trim(),
        source_version: plan.boundary_rule_set.source_version.trim(),
      } : null,
    });
    try {
      const accepted = await client.composeSitePlan(
        sourceVersionId,
        expected,
        `mobile-site-${sourceVersionId}-${Date.now()}`,
      );
      const job = await client.waitForJob(accepted.job_id, {
        intervalMs: 1_000,
        timeoutMs: 8 * 60_000,
      });
      if (!mounted.current) return;
      const versionId = verifiedSitePlanJobVersionId(job, accepted.job_id, sourceVersionId, expected);
      if (!versionId) {
        const message = (job.error as { message?: unknown } | null)?.message;
        throw new Error(typeof message === "string" ? message : "Сервер не подтвердил новый участок.");
      }
      const version = await client.getVersion(versionId);
      if (!mounted.current) return;
      if (!verifiedSitePlanVersion(version, versionId, projectId, sourceVersionId, expected)) {
        throw new Error("Новая версия участка не совпала с отправленным планом.");
      }
      onApplied(version);
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  const rules = plan.boundary_rule_set;
  return (
    <View style={[styles.card, { gap: 14 }]} accessibilityLabel="Создание участка">
      <View style={{ gap: 4 }}>
        <Text style={styles.heading}>Участок вокруг дома</Text>
        <Text style={styles.muted}>
          Сервер создаст новую immutable-версию с рельефом, площадкой дома, дорожкой и выбранными сторонами забора.
          Это геометрическая компоновка, а не геодезия или проверка строительных норм.
        </Text>
      </View>

      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        disabled={busy}
        onPress={() => setOpen((value) => !value)}
        style={styles.button}
      >
        <Text style={styles.buttonText}>{open ? "Свернуть настройки" : "Настроить участок"}</Text>
      </Pressable>

      {open ? (
        <>

      <Text style={styles.heading}>Границы и дом</Text>
      <View style={[styles.row, { flexWrap: "wrap" }]}>
        <NumberField label="Длина участка, мм" value={plan.plot_length_mm} disabled={busy} onChange={(value) => update("plot_length_mm", value)} />
        <NumberField label="Ширина участка, мм" value={plan.plot_width_mm} disabled={busy} onChange={(value) => update("plot_width_mm", value)} />
        <NumberField label="Дом X, мм" value={plan.house_x_mm} disabled={busy} onChange={(value) => update("house_x_mm", value)} />
        <NumberField label="Дом Y, мм" value={plan.house_y_mm} disabled={busy} onChange={(value) => update("house_y_mm", value)} />
        <NumberField label="Поворот дома, °" value={plan.house_rotation_deg} disabled={busy} onChange={(value) => update("house_rotation_deg", value)} />
        <NumberField label="Минимальный отступ, мм" value={plan.minimum_boundary_clearance_mm ?? 500} disabled={busy} onChange={(value) => update("minimum_boundary_clearance_mm", value)} />
      </View>

      <Text style={styles.heading}>Отметки углов рельефа</Text>
      <View style={[styles.row, { flexWrap: "wrap" }]}>
        {plan.corner_elevations_mm.map((elevation, index) => (
          <NumberField
            key={index}
            label={`${index + 1}-й угол, мм`}
            value={elevation}
            disabled={busy}
            onChange={(value) => {
              const next = [...plan.corner_elevations_mm];
              next[index] = value;
              update("corner_elevations_mm", next);
            }}
          />
        ))}
      </View>

      <View style={{ gap: 9 }}>
        <View style={[styles.row, { justifyContent: "space-between" }]}>
          <Text style={styles.heading}>Дорожка · {plan.path_points_mm.length} точек</Text>
          <Pressable
            accessibilityRole="button"
            disabled={busy || plan.path_points_mm.length >= 16}
            onPress={() => update("path_points_mm", [...plan.path_points_mm, [...plan.path_points_mm.at(-1)!]])}
            style={[styles.chip, (busy || plan.path_points_mm.length >= 16) && { opacity: 0.45 }]}
          >
            <Text style={styles.chipText}>+ точка</Text>
          </Pressable>
        </View>
        {plan.path_points_mm.map((point, index) => (
          <View key={index} style={[styles.row, { alignItems: "flex-end" }]}>
            <NumberField label={`Точка ${index + 1} · X, мм`} value={point[0]!} disabled={busy} onChange={(value) => {
              const next = plan.path_points_mm.map((item) => [...item]);
              next[index]![0] = value;
              update("path_points_mm", next);
            }} />
            <NumberField label={`Точка ${index + 1} · Y, мм`} value={point[1]!} disabled={busy} onChange={(value) => {
              const next = plan.path_points_mm.map((item) => [...item]);
              next[index]![1] = value;
              update("path_points_mm", next);
            }} />
            {index === plan.path_points_mm.length - 1 && plan.path_points_mm.length > 2 ? (
              <Pressable accessibilityRole="button" disabled={busy} onPress={() => update("path_points_mm", plan.path_points_mm.slice(0, -1))} style={styles.chip}>
                <Text style={styles.chipText}>Убрать</Text>
              </Pressable>
            ) : null}
          </View>
        ))}
        <NumberField label="Ширина дорожки, мм" value={plan.path_width_mm} disabled={busy} onChange={(value) => update("path_width_mm", value)} />
      </View>

      <Text style={styles.heading}>Забор</Text>
      <View style={[styles.row, { flexWrap: "wrap" }]}>
        {SITE_SIDES.map((side) => (
          <Pressable
            key={side}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: plan.fence_sides.includes(side), disabled: busy }}
            disabled={busy}
            onPress={() => toggleFence(side)}
            style={[styles.chip, plan.fence_sides.includes(side) && { borderColor: colors.accent, backgroundColor: colors.accentWash }]}
          >
            <Text style={styles.chipText}>{SIDE_LABELS[side]}</Text>
          </Pressable>
        ))}
      </View>
      <View style={[styles.row, { flexWrap: "wrap" }]}>
        <NumberField label="Высота забора, мм" value={plan.fence_height_mm} disabled={busy} onChange={(value) => update("fence_height_mm", value)} />
        <NumberField label="Шаг столбов, мм" value={plan.fence_post_spacing_mm} disabled={busy} onChange={(value) => update("fence_post_spacing_mm", value)} />
      </View>

      <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: Boolean(rules), disabled: busy }} disabled={busy} onPress={() => setRulesEnabled(!rules)} style={styles.button}>
        <Text style={styles.buttonText}>{rules ? "✓ " : ""}Указать owner-declared правила границ</Text>
      </Pressable>
      {rules ? (
        <View style={{ gap: 9 }}>
          <Text style={styles.muted}>
            Источник сохраняется как заявление владельца и не считается проверенной нормативной базой.
          </Text>
          {([
            ["Юрисдикция", "jurisdiction", rules.jurisdiction],
            ["Название документа", "title", rules.title],
            ["HTTPS-источник", "source_url", rules.source_url],
            ["Версия источника", "source_version", rules.source_version],
            ["Дата YYYY-MM-DD", "effective_date", rules.effective_date],
          ] as const).map(([label, key, value]) => (
            <TextInput
              key={key}
              accessibilityLabel={label}
              autoCapitalize={key === "source_url" ? "none" : "sentences"}
              editable={!busy}
              onChangeText={(text) => update("boundary_rule_set", { ...rules, [key]: text })}
              placeholder={label}
              placeholderTextColor={colors.muted}
              style={styles.input}
              value={value}
            />
          ))}
          <View style={[styles.row, { flexWrap: "wrap" }]}>
            {SITE_SIDES.map((side) => (
              <NumberField
                key={side}
                label={`${SIDE_LABELS[side]} · отступ, мм`}
                value={rules.required_clearances_mm[side]}
                disabled={busy}
                onChange={(value) => update("boundary_rule_set", {
                  ...rules,
                  required_clearances_mm: { ...rules.required_clearances_mm, [side]: value },
                })}
              />
            ))}
          </View>
        </View>
      ) : null}

      {error ? <Text accessibilityLiveRegion="polite" style={[styles.sectionSubtitle, { color: colors.red }]}>{error}</Text> : null}
      <Pressable accessibilityRole="button" disabled={busy} onPress={() => void compose()} style={[styles.button, styles.buttonPrimary, busy && { opacity: 0.5 }]}>
        <Text style={styles.buttonText}>{busy ? "Собираем участок…" : "Создать новую версию участка"}</Text>
      </Pressable>
        </>
      ) : null}
    </View>
  );
}
