import type { PrinterBridge, PrinterProfile, PrinterState } from "@physical-ai/contracts";
import { useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Image, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/src/session";
import { colors, radii, styles } from "@/src/theme";

function duration(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0 || !Number.isFinite(seconds)) return "—";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.ceil((seconds % 3600) / 60);
  return hours > 0 ? `${hours} ч ${minutes} мин` : `${minutes} мин`;
}

function blobDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Не удалось прочитать снимок камеры."));
    reader.onload = () => typeof reader.result === "string"
      ? resolve(reader.result)
      : reject(new Error("Камера вернула неподдерживаемый снимок."));
    reader.readAsDataURL(blob);
  });
}

export default function PrintMonitorScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { client, session } = useSession();
  const [profile, setProfile] = useState<PrinterProfile | null>(null);
  const [bridge, setBridge] = useState<PrinterBridge | null>(null);
  const [state, setState] = useState<PrinterState | null>(null);
  const [cameraUri, setCameraUri] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [controlling, setControlling] = useState<"pause" | "resume" | "cancel" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshState = useCallback(async (manual = false) => {
    if (!client || !session || !id) return;
    if (manual) setRefreshing(true);
    try {
      const [profiles, capability] = await Promise.all([
        client.listPrinterProfiles(session.workspaceId),
        client.getPrinterBridge(),
      ]);
      const current = profiles.find((item) => item.id === id) ?? null;
      if (!current) throw new Error("Профиль принтера не найден в текущем рабочем пространстве.");
      setProfile(current);
      setBridge(capability);
      setState(capability.enabled ? await client.getPrinterState(id) : null);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [client, id, session]);

  const refreshCamera = useCallback(async () => {
    if (!client || !id || bridge?.has_camera !== true || bridge.test_mode) return;
    try {
      setCameraUri(await blobDataUrl(await client.getPrinterCamera(id)));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [bridge?.has_camera, bridge?.test_mode, client, id]);

  const control = useCallback(async (action: "pause" | "resume" | "cancel") => {
    if (!client || !id || bridge?.provider !== "octoprint") return;
    setControlling(action);
    try {
      setState(await client.controlPrinter(id, action));
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setControlling(null);
    }
  }, [bridge?.provider, client, id]);

  const confirmCancel = useCallback(() => {
    Alert.alert(
      "Отменить текущую печать?",
      "OctoPrint остановит активное задание. Это действие нельзя возобновить.",
      [
        { text: "Не отменять", style: "cancel" },
        { text: "Остановить печать", style: "destructive", onPress: () => void control("cancel") },
      ],
    );
  }, [control]);

  useEffect(() => {
    void refreshState();
    const timer = setInterval(() => void refreshState(), 5000);
    return () => clearInterval(timer);
  }, [refreshState]);

  useEffect(() => {
    void refreshCamera();
    if (!bridge?.has_camera || bridge.test_mode) return undefined;
    const timer = setInterval(() => void refreshCamera(), 15000);
    return () => clearInterval(timer);
  }, [bridge?.has_camera, bridge?.test_mode, refreshCamera]);

  if (loading) {
    return <View style={[styles.screen, { alignItems: "center", justifyContent: "center" }]}><ActivityIndicator color={colors.accent} /></View>;
  }

  const progress = state?.completion_pct == null ? null : Math.max(0, Math.min(100, state.completion_pct));
  return (
    <SafeAreaView style={styles.screen} edges={["bottom"]}>
      <ScrollView contentContainerStyle={{ width: "100%", maxWidth: 900, alignSelf: "center", padding: 16, paddingBottom: 32, gap: 14 }}>
        <View style={{ gap: 5 }}>
          <Text style={[styles.title, { fontSize: 29 }]}>Контроль печати</Text>
          <Text style={styles.muted}>{profile?.name ?? "Принтер"} · состояние от защищённого серверного моста</Text>
        </View>

        {bridge?.test_mode ? (
          <View style={[styles.card, { borderColor: colors.yellow, backgroundColor: colors.yellowWash }]}>
            <Text style={[styles.heading, { color: colors.yellow }]}>DEMO · реальный принтер не подключён</Text>
            <Text style={styles.muted}>Показанные состояние и температуры созданы тестовым bridge и не являются телеметрией устройства.</Text>
          </View>
        ) : null}
        {bridge && !bridge.enabled ? (
          <View style={[styles.card, { borderColor: colors.yellow, backgroundColor: colors.yellowWash }]}>
            <Text style={[styles.heading, { color: colors.yellow }]}>Подключение к принтеру не настроено</Text>
            <Text style={styles.muted}>Адрес и ключ контроллера задаются только на сервере; приложение не просит и не хранит их.</Text>
          </View>
        ) : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}

        <View style={[styles.card, { borderRadius: radii.feature, gap: 14 }]}>
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <View style={{ flex: 1, gap: 4 }}>
              <Text style={styles.sectionTitle}>{state?.state ?? "Состояние недоступно"}</Text>
              <Text style={styles.muted}>{state?.filename ?? "Файл печати не выбран"}</Text>
            </View>
            <View style={[styles.statusBadge, { backgroundColor: state?.printing ? colors.greenWash : colors.panel2 }]}>
              <View style={[styles.statusDot, { backgroundColor: state?.printing ? colors.green : state?.paused ? colors.yellow : colors.muted }]} />
              <Text style={[styles.statusText, { color: state?.printing ? colors.green : state?.paused ? colors.yellow : colors.muted }]}>
                {state?.printing ? "Печатает" : state?.paused ? "Пауза" : state?.operational ? "Готов" : "Не готов"}
              </Text>
            </View>
          </View>

          {progress != null ? (
            <View style={{ gap: 7 }}>
              <View style={[styles.row, { justifyContent: "space-between" }]}>
                <Text style={styles.heading}>Прогресс</Text>
                <Text style={[styles.title, { color: colors.accent }]}>{progress.toFixed(1)}%</Text>
              </View>
              <View style={{ height: 10, borderRadius: 5, overflow: "hidden", backgroundColor: colors.panel2 }}>
                <View style={{ width: `${progress}%`, height: "100%", backgroundColor: colors.accent }} />
              </View>
              <Text style={styles.muted}>Прошло {duration(state?.elapsed_seconds)} · осталось {duration(state?.remaining_seconds)}</Text>
            </View>
          ) : <Text style={styles.muted}>Контроллер пока не сообщает процент выполнения.</Text>}
        </View>

        <View style={[styles.row, { alignItems: "stretch" }]}>
          <View style={[styles.card, { flex: 1, minWidth: 150, borderRadius: radii.section }]}>
            <Text style={styles.sectionSubtitle}>Сопло</Text>
            <Text style={styles.sectionTitle}>{state?.nozzle_actual_c?.toFixed(0) ?? "—"} °C</Text>
            <Text style={styles.muted}>Цель {state?.nozzle_target_c?.toFixed(0) ?? "—"} °C</Text>
          </View>
          <View style={[styles.card, { flex: 1, minWidth: 150, borderRadius: radii.section }]}>
            <Text style={styles.sectionSubtitle}>Стол</Text>
            <Text style={styles.sectionTitle}>{state?.bed_actual_c?.toFixed(0) ?? "—"} °C</Text>
            <Text style={styles.muted}>Цель {state?.bed_target_c?.toFixed(0) ?? "—"} °C</Text>
          </View>
        </View>

        {bridge?.provider === "octoprint" && (state?.printing || state?.paused) ? (
          <View style={[styles.card, { borderRadius: radii.section, gap: 10 }]}>
            <Text style={styles.sectionTitle}>Управление заданием</Text>
            <Text style={styles.muted}>Команды передаются в настроенный оператором OctoPrint. Состояние после команды повторно читается с контроллера.</Text>
            <View style={[styles.row, { alignItems: "stretch" }]}>
              {state.paused ? (
                <Pressable disabled={controlling !== null} onPress={() => void control("resume")} style={[styles.button, styles.buttonPrimary, { flex: 1 }, controlling !== null && { opacity: 0.5 }]}>
                  <Text style={styles.buttonText}>{controlling === "resume" ? "Возобновляем…" : "Продолжить"}</Text>
                </Pressable>
              ) : (
                <Pressable disabled={controlling !== null} onPress={() => void control("pause")} style={[styles.button, { flex: 1 }, controlling !== null && { opacity: 0.5 }]}>
                  <Text style={styles.buttonText}>{controlling === "pause" ? "Приостанавливаем…" : "Пауза"}</Text>
                </Pressable>
              )}
              <Pressable disabled={controlling !== null} onPress={confirmCancel} style={[styles.button, { flex: 1, borderColor: colors.red }, controlling !== null && { opacity: 0.5 }]}>
                <Text style={[styles.buttonText, { color: colors.red }]}>{controlling === "cancel" ? "Останавливаем…" : "Отменить печать"}</Text>
              </Pressable>
            </View>
          </View>
        ) : null}

        {bridge?.has_camera ? (
          <View style={[styles.card, { borderRadius: radii.feature }]}>
            <Text style={styles.sectionTitle}>Камера принтера</Text>
            {bridge.test_mode ? (
              <View style={{ height: 220, borderRadius: radii.preview, backgroundColor: colors.viewport, alignItems: "center", justifyContent: "center", padding: 20 }}>
                <Text style={[styles.heading, { color: colors.yellow }]}>DEMO CAMERA</Text>
                <Text style={[styles.muted, { textAlign: "center" }]}>Снимок не запрашивается: тестовый bridge не связывается с камерой.</Text>
              </View>
            ) : cameraUri ? (
              <Image accessibilityLabel="Снимок камеры принтера" source={{ uri: cameraUri }} resizeMode="contain" style={{ width: "100%", aspectRatio: 16 / 9, borderRadius: radii.preview, backgroundColor: colors.viewport }} />
            ) : <Text style={styles.muted}>Получаем защищённый снимок через сервер…</Text>}
          </View>
        ) : null}

        <Pressable disabled={refreshing} onPress={() => { void refreshState(true); void refreshCamera(); }} style={[styles.button, styles.buttonPrimary, refreshing && { opacity: 0.5 }]}>
          <Text style={styles.buttonText}>{refreshing ? "Обновляем…" : "Обновить сейчас"}</Text>
        </Pressable>
        <Text style={styles.muted}>Статус обновляется каждые 5 секунд, камера — каждые 15 секунд. Управление доступно только для реального OctoPrint, не в DEMO. Номер слоя, автоматическое распознавание ошибок и timelapse не показываются, пока контроллер не предоставляет проверяемые данные.</Text>
      </ScrollView>
    </SafeAreaView>
  );
}
