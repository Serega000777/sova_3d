import type {
  FacadeCompatibility,
  FacadeFitAccepted,
  FitTestReport,
  PhysicalAiClient,
  Project,
} from "@physical-ai/contracts";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";

import { colors, styles } from "./theme";

function acceptedMatches(
  accepted: FacadeFitAccepted,
  targetVersionId: string,
  openingId: string,
  sourceVersionId: string,
) {
  return accepted.target_version_id === targetVersionId
    && accepted.opening_id === openingId
    && accepted.source_version_id === sourceVersionId
    && accepted.placement.align === "centre"
    && accepted.limitations.length > 0;
}

export function MarketplaceFacadePlacement({
  client,
  orderId,
  project,
  compatibility,
}: {
  client: PhysicalAiClient;
  orderId: string;
  project: Project;
  compatibility: FacadeCompatibility;
}) {
  const router = useRouter();
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [fitTestId, setFitTestId] = useState<string | null>(null);
  const [report, setReport] = useState<FitTestReport | null>(null);
  const [limitations, setLimitations] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function run(openingId: string, sourceVersionId: string) {
    if (!project.head_version_id) return;
    const key = `${openingId}:${sourceVersionId}`;
    setBusyKey(key);
    setError(null);
    setFitTestId(null);
    setReport(null);
    try {
      const accepted = await client.startMarketplaceFacadeFit(orderId, {
        target_project_id: project.id,
        opening_id: openingId,
        source_version_id: sourceVersionId,
        language: "ru",
      });
      if (!acceptedMatches(accepted, project.head_version_id, openingId, sourceVersionId)) {
        throw new Error("Сервер вернул проверку не для выбранного проёма или версии фасада.");
      }
      const job = await client.waitForJob(accepted.job_id, { timeoutMs: 8 * 60_000 });
      if (job.status !== "succeeded") {
        throw new Error((job.error as { message?: string } | null)?.message
          ?? "Адресная проверка не выполнена.");
      }
      const result = job.result as {
        fit_test_id?: unknown;
        version_a_id?: unknown;
        report?: FitTestReport;
      } | null;
      if (result?.version_a_id !== project.head_version_id
        || typeof result.fit_test_id !== "string"
        || !result.report?.measured?.b_transform) {
        throw new Error("Результат не содержит доказанную позу выбранного фасада.");
      }
      setFitTestId(result.fit_test_id);
      setReport(result.report);
      setLimitations(accepted.limitations);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusyKey(null);
    }
  }

  async function save() {
    if (!fitTestId) return;
    setBusyKey("save");
    setError(null);
    try {
      const scene = await client.createFitAssembly(
        fitTestId,
        "Адресное размещение фасадного элемента",
      );
      router.push(`/project/${project.id}?version=${scene.version_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusyKey(null);
    }
  }

  const verdict = report?.measured.verdict;
  return (
    <View style={[styles.card, { gap: 10, borderColor: colors.accent }]}>
      <Text style={styles.heading}>Адресное размещение после покупки</Text>
      <Text style={styles.sectionSubtitle}>
        Модуль ставится на среднюю плоскость сохранённого opening_id; затем сервер измеряет реальные mesh‑коллизии.
      </Text>
      {compatibility.openings.flatMap((opening) => opening.matches.map((match) => {
        const key = `${opening.opening_id}:${match.version_id}`;
        return (
          <View key={key} style={{ gap: 6 }}>
            <Text style={styles.sectionSubtitle}>
              {opening.opening_id} · {opening.side} · {opening.width_mm.toFixed(0)} × {opening.height_mm.toFixed(0)} мм · {match.label}
            </Text>
            <Pressable
              accessibilityRole="button"
              disabled={busyKey !== null}
              onPress={() => void run(opening.opening_id, match.version_id)}
              style={({ pressed }) => [styles.button, (pressed || busyKey !== null) && { opacity: 0.65 }]}
            >
              <Text style={styles.buttonText}>{busyKey === key ? "Проверяем…" : "Проверить этот проём"}</Text>
            </Pressable>
          </View>
        );
      }))}
      {report ? (
        <View style={{ gap: 6 }}>
          <Text style={[styles.heading, { color: verdict === "collides" ? colors.red : colors.green }]}>Результат: {verdict}</Text>
          <Text style={styles.sectionSubtitle}>{report.advice.summary}</Text>
          <Text style={styles.sectionSubtitle}>
            Проникновение {report.measured.max_penetration_mm.toFixed(3)} мм
            {report.measured.min_clearance_mm !== null ? ` · зазор ${report.measured.min_clearance_mm.toFixed(3)} мм` : ""}
          </Text>
          {limitations.map((item) => <Text key={item} style={styles.sectionSubtitle}>• {item}</Text>)}
          {fitTestId && verdict !== "collides" ? (
            <Pressable
              accessibilityRole="button"
              disabled={busyKey !== null}
              onPress={() => void save()}
              style={({ pressed }) => [styles.button, (pressed || busyKey !== null) && { opacity: 0.65 }]}
            >
              <Text style={styles.buttonText}>{busyKey === "save" ? "Сохраняем…" : "Сохранить immutable‑размещение"}</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}
