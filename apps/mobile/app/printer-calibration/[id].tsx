import type { CalibrationMeasurements, PrinterProfile } from "@physical-ai/contracts";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/src/session";
import { colors, radii, styles } from "@/src/theme";

type MeasurementKey = keyof CalibrationMeasurements;

const FEATURES: { id: MeasurementKey; label: string; nominal: number; hint: string }[] = [
  { id: "hole_3_mm", label: "Отверстие Ø3", nominal: 3, hint: "Внутренний диаметр" },
  { id: "hole_5_mm", label: "Отверстие Ø5", nominal: 5, hint: "Внутренний диаметр" },
  { id: "hole_8_mm", label: "Отверстие Ø8", nominal: 8, hint: "Внутренний диаметр" },
  { id: "peg_5_mm", label: "Штифт Ø5", nominal: 5, hint: "Наружный диаметр" },
  { id: "peg_8_mm", label: "Штифт Ø8", nominal: 8, hint: "Наружный диаметр" },
  { id: "length_60_mm", label: "Длина 60", nominal: 60, hint: "Длинная сторона" },
  { id: "wall_mm", label: "Тонкая стенка", nominal: 0.8, hint: "Две линии сопла" },
];

function learnedNumber(calibration: Record<string, unknown>, key: string): number | null {
  const value = calibration[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export default function PrinterCalibrationScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { client, session } = useSession();
  const [profile, setProfile] = useState<PrinterProfile | null>(null);
  const [values, setValues] = useState<Partial<Record<MeasurementKey, string>>>({});
  const [projectId, setProjectId] = useState<string | null>(null);
  const [busy, setBusy] = useState<"coupon" | "save" | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client || !session || !id) return;
    try {
      const profiles = await client.listPrinterProfiles(session.workspaceId);
      const current = profiles.find((item) => item.id === id) ?? null;
      setProfile(current);
      if (!current) setError("Профиль принтера не найден в текущем рабочем пространстве.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [client, id, session]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function createCoupon() {
    if (!client || !profile || busy) return;
    setBusy("coupon");
    setError(null);
    setProjectId(null);
    try {
      const started = await client.startCalibrationPrint(profile.id);
      const job = await client.waitForJob(started.job.job_id);
      if (job.status !== "succeeded") throw new Error("Не удалось создать модель калибровочного образца.");
      setProjectId(started.project_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function saveMeasurements() {
    if (!client || !profile || busy) return;
    const measurements: CalibrationMeasurements = {};
    for (const feature of FEATURES) {
      const raw = values[feature.id]?.trim();
      if (!raw) continue;
      const parsed = Number(raw.replace(",", "."));
      if (!Number.isFinite(parsed) || parsed <= 0) {
        setError(`Проверьте измерение «${feature.label}».`);
        return;
      }
      measurements[feature.id] = parsed;
    }
    if (Object.keys(measurements).length === 0) {
      setError("Введите хотя бы одно измерение штангенциркулем.");
      return;
    }
    setBusy("save");
    setError(null);
    try {
      const updated = await client.recordCalibration(profile.id, measurements);
      setProfile(updated);
      setValues({});
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return <View style={[styles.screen, { alignItems: "center", justifyContent: "center" }]}><ActivityIndicator color={colors.accent} /></View>;
  }

  const learned = (profile?.calibration ?? {}) as Record<string, unknown>;
  const summary = [
    ["Отверстия", learnedNumber(learned, "hole_undersize_mm"), "мм меньше"],
    ["Штифты", learnedNumber(learned, "peg_oversize_mm"), "мм больше"],
    ["XY-компенсация", learnedNumber(learned, "xy_compensation_mm"), "мм на сторону"],
    ["Усадка", learnedNumber(learned, "shrinkage_pct"), "%"],
    ["Поток", learnedNumber(learned, "flow_pct"), "%"],
  ] as const;
  const hasLearned = summary.some(([, value]) => value != null);

  return (
    <SafeAreaView style={styles.screen} edges={["bottom"]}>
      <ScrollView contentContainerStyle={{ width: "100%", maxWidth: 820, alignSelf: "center", padding: 16, paddingBottom: 36, gap: 14 }} keyboardShouldPersistTaps="handled">
        <View style={{ gap: 5 }}>
          <Text style={[styles.title, { fontSize: 29 }]}>Калибровка печати</Text>
          <Text style={styles.muted}>{profile?.name ?? "Профиль"} · образец → измерения → результат</Text>
        </View>

        <View style={styles.row}>
          {["1 · Образец", "2 · Измерения", "3 · Результат"].map((step, index) => (
            <View key={step} style={[styles.chip, { borderColor: index === 0 && !projectId ? colors.accent : index === 1 && projectId && !hasLearned ? colors.accent : index === 2 && hasLearned ? colors.green : colors.border }]}>
              <Text style={styles.chipText}>{step}</Text>
            </View>
          ))}
        </View>

        <View style={[styles.card, { borderRadius: radii.feature }]}>
          <Text style={styles.sectionTitle}>Калибровочный образец</Text>
          <Text style={styles.muted}>Создадим отдельный проект с отверстиями Ø3/5/8 мм, штифтами Ø5/8 мм, стороной 60 мм и тонкой стенкой. Затем подготовьте и напечатайте его обычным путём.</Text>
          <Pressable disabled={Boolean(busy) || !profile} onPress={() => void createCoupon()} style={[styles.button, styles.buttonPrimary, (Boolean(busy) || !profile) && { opacity: 0.45 }]}>
            <Text style={styles.buttonText}>{busy === "coupon" ? "Создаём модель…" : projectId ? "Создать образец снова" : "Создать модель образца"}</Text>
          </Pressable>
          {projectId ? (
            <Pressable onPress={() => router.push(`/project/${projectId}`)} style={[styles.button, { borderColor: colors.accent }]}>
              <Text style={[styles.buttonText, { color: colors.accent }]}>Открыть проект образца</Text>
            </Pressable>
          ) : null}
          <Text style={styles.sectionSubtitle}>Создание модели не запускает физический принтер и не отправляет G-code автоматически.</Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Измерения штангенциркулем</Text>
          <Text style={styles.muted}>Можно сохранить часть измерений. Сервер отклонит неправдоподобное отклонение, не меняя профиль.</Text>
          <View style={[styles.row, { alignItems: "stretch" }]}>
            {FEATURES.map((feature) => (
              <View key={feature.id} style={{ flexGrow: 1, flexBasis: 210, gap: 5 }}>
                <Text style={styles.heading}>{feature.label} <Text style={styles.muted}>({feature.nominal} мм)</Text></Text>
                <Text style={styles.sectionSubtitle}>{feature.hint}</Text>
                <TextInput
                  accessibilityLabel={feature.label}
                  inputMode="decimal"
                  placeholder={String(feature.nominal).replace(".", ",")}
                  placeholderTextColor={colors.muted}
                  value={values[feature.id] ?? ""}
                  onChangeText={(value) => setValues((current) => ({ ...current, [feature.id]: value }))}
                  style={styles.input}
                />
              </View>
            ))}
          </View>
          <Pressable disabled={Boolean(busy)} onPress={() => void saveMeasurements()} style={[styles.button, styles.buttonPrimary, Boolean(busy) && { opacity: 0.45 }]}>
            <Text style={styles.buttonText}>{busy === "save" ? "Сохраняем…" : "Сохранить измерения"}</Text>
          </Pressable>
        </View>

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <View style={[styles.card, { borderColor: hasLearned ? colors.green : colors.border }]}>
          <Text style={styles.sectionTitle}>Результат профиля</Text>
          {hasLearned ? summary.map(([label, value, unit]) => value == null ? null : (
            <View key={label} style={[styles.row, { justifyContent: "space-between", borderBottomWidth: 1, borderBottomColor: colors.border, paddingVertical: 7 }]}>
              <Text style={styles.muted}>{label}</Text>
              <Text style={[styles.heading, { color: colors.green }]}>{value > 0 ? "+" : ""}{value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "")} {unit}</Text>
            </View>
          )) : <Text style={styles.muted}>Пока нет сохранённых измерений. Непроверенные параметры не считаются откалиброванными.</Text>}
          <Text style={styles.sectionSubtitle}>Компенсации применяются к будущей подготовке печати этого профиля. Они не исправляют уже созданный G-code.</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
