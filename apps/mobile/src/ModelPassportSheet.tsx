/** A shareable, version-scoped summary built only from canonical project data. */
import type {
  IntegrityReport,
  ProjectSummary,
  Version,
  VersionHistoryItem,
} from "@physical-ai/contracts";
import { Pressable, ScrollView, Share, Text, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, radii, styles } from "./theme";

export interface ModelPassportData {
  projectName: string;
  projectId: string;
  description: string | null;
  versionId: string;
  sequenceNo: number;
  author: string;
  createdAt: string;
  state: string;
  storedFileCount: number;
  storedBytes: number | null;
  measuredTriangles: number | null;
  integrity: "passed" | "warning" | "failed" | "not_checked";
  dimensionsMm: number[] | null;
}

function positiveInteger(value: unknown): number | null {
  return Number.isInteger(value) && (value as number) > 0 ? value as number : null;
}

export function modelPassportData(
  project: ProjectSummary,
  version: Version,
  history: VersionHistoryItem | null,
  report: IntegrityReport | null,
): ModelPassportData {
  const integrity = !report
    ? "not_checked"
    : report.status === "fail"
      ? "failed"
      : report.status === "warn"
        ? "warning"
        : "passed";
  return {
    projectName: project.name,
    projectId: project.id,
    description: project.description?.trim() || null,
    versionId: version.id,
    sequenceNo: version.sequence_no,
    author: history?.creator_name ?? (version.created_by ? version.created_by.slice(0, 8) : "Система"),
    createdAt: version.created_at,
    state: version.state,
    storedFileCount: version.assets.length,
    storedBytes: history && Number.isInteger(history.total_asset_bytes) && history.total_asset_bytes >= 0
      ? history.total_asset_bytes
      : null,
    measuredTriangles: positiveInteger(report?.output.faces),
    integrity,
    dimensionsMm: report?.output.bboxSizeMm ?? null,
  };
}

function formatBytes(bytes: number, language: "ru" | "en"): string {
  if (bytes < 1024) return `${bytes} ${language === "ru" ? "Б" : "B"}`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} ${language === "ru" ? "КБ" : "KB"}`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} ${language === "ru" ? "МБ" : "MB"}`;
}

export function modelPassportText(data: ModelPassportData, language: "ru" | "en"): string {
  const ru = language === "ru";
  const status = {
    passed: ru ? "проверена" : "passed",
    warning: ru ? "с замечаниями" : "warning",
    failed: ru ? "не прошла проверку" : "failed",
    not_checked: ru ? "не проверялась" : "not checked",
  }[data.integrity];
  const dimensions = data.dimensionsMm
    ? `${data.dimensionsMm.map((value) => Math.round(value * 100) / 100).join(" × ")} ${ru ? "мм" : "mm"}`
    : ru ? "не измерены" : "not measured";
  return [
    ru ? "Паспорт 3D-модели Sova 3D" : "Sova 3D model passport",
    `${ru ? "Проект" : "Project"}: ${data.projectName}`,
    ...(data.description ? [`${ru ? "Описание" : "Description"}: ${data.description}`] : []),
    `${ru ? "ID проекта" : "Project ID"}: ${data.projectId}`,
    `${ru ? "Версия" : "Version"}: v${data.sequenceNo} (${data.versionId})`,
    `${ru ? "Автор версии" : "Version author"}: ${data.author}`,
    `${ru ? "Создана" : "Created"}: ${new Date(data.createdAt).toLocaleString(ru ? "ru-RU" : "en-US")}`,
    `${ru ? "Статус версии" : "Version state"}: ${data.state}`,
    `${ru ? "Проверка целостности" : "Integrity check"}: ${status}`,
    `${ru ? "Габариты" : "Dimensions"}: ${dimensions}`,
    `${ru ? "Сохранённых файлов" : "Stored files"}: ${data.storedFileCount}`,
    ...(data.storedBytes !== null ? [`${ru ? "Размер сохранённых файлов" : "Stored file bytes"}: ${formatBytes(data.storedBytes, language)}`] : []),
    ...(data.measuredTriangles !== null ? [`${ru ? "Измеренных треугольников" : "Measured triangles"}: ${data.measuredTriangles.toLocaleString(ru ? "ru-RU" : "en-US")}`] : []),
    ru
      ? "Экспорт: STL, 3MF, GLB, FBX и USDZ; STEP/IGES — только для точной CAD-геометрии."
      : "Exports: STL, 3MF, GLB, FBX and USDZ; STEP/IGES require exact CAD geometry.",
  ].join("\n");
}

export function ModelPassportSheet({
  visible,
  language,
  project,
  version,
  history,
  report,
  busy,
  onClose,
  onOpenCheck,
  onShareIntegrityPdf,
}: {
  visible: boolean;
  language: "ru" | "en";
  project: ProjectSummary | null;
  version: Version | null;
  history: VersionHistoryItem | null;
  report: IntegrityReport | null;
  busy: boolean;
  onClose: () => void;
  onOpenCheck: () => void;
  onShareIntegrityPdf: () => void;
}) {
  const ru = language === "ru";
  const data = project && version ? modelPassportData(project, version, history, report) : null;
  const tone = data?.integrity === "passed"
    ? colors.green
    : data?.integrity === "failed"
      ? colors.red
      : colors.yellow;
  const status = data?.integrity === "passed"
    ? (ru ? "Проверена" : "Passed")
    : data?.integrity === "warning"
      ? (ru ? "С замечаниями" : "Warning")
      : data?.integrity === "failed"
        ? (ru ? "Не прошла проверку" : "Failed")
        : (ru ? "Не проверялась" : "Not checked");

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="92%"
      tabletWidth={560}
      accessibilityLabel={ru ? "Закрыть паспорт модели" : "Close model passport"}
      contentGap={12}
    >
      <View style={{ flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.title}>{ru ? "Паспорт 3D-модели" : "3D model passport"}</Text>
          <Text style={styles.sectionSubtitle}>
            {ru ? "Канонические данные выбранной неизменяемой версии." : "Canonical data for the selected immutable version."}
          </Text>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel={ru ? "Закрыть" : "Close"} hitSlop={12} onPress={onClose}>
          <Text style={[styles.sectionTitle, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>

      {!data ? (
        <Text style={styles.muted}>{ru ? "Сначала откройте версию модели." : "Open a model version first."}</Text>
      ) : (
        <ScrollView contentContainerStyle={{ gap: 12 }} showsVerticalScrollIndicator={false}>
          <View style={{ gap: 4, padding: 14, borderRadius: radii.section, borderWidth: 1, borderColor: tone, backgroundColor: colors.panel2 }}>
            <Text style={[styles.heading, { color: tone }]}>{status}</Text>
            <Text style={styles.muted}>
              {report
                ? (ru ? "Статус относится только к этой выбранной версии." : "This status applies only to the selected version.")
                : (ru ? "Запустите проверку — паспорт не подменяет её зелёным статусом." : "Run the check; the passport does not invent a green status.")}
            </Text>
          </View>

          <View style={[styles.card, { gap: 10 }]}>
            <PassportRow label={ru ? "Название" : "Name"} value={data.projectName} />
            {data.description ? <PassportRow label={ru ? "Описание" : "Description"} value={data.description} /> : null}
            <PassportRow label={ru ? "ID проекта" : "Project ID"} value={data.projectId} mono />
            <PassportRow label={ru ? "Версия" : "Version"} value={`v${data.sequenceNo} · ${data.versionId}`} mono />
            <PassportRow label={ru ? "Автор версии" : "Version author"} value={data.author} />
            <PassportRow label={ru ? "Создана" : "Created"} value={new Date(data.createdAt).toLocaleString(ru ? "ru-RU" : "en-US")} />
            <PassportRow label={ru ? "Сохранённых файлов" : "Stored files"} value={String(data.storedFileCount)} />
            {data.storedBytes !== null ? (
              <PassportRow label={ru ? "Размер сохранённых файлов" : "Stored file bytes"} value={formatBytes(data.storedBytes, language)} />
            ) : null}
            {data.measuredTriangles !== null ? (
              <PassportRow label={ru ? "Измеренных треугольников" : "Measured triangles"} value={data.measuredTriangles.toLocaleString(ru ? "ru-RU" : "en-US")} />
            ) : null}
            <PassportRow
              label={ru ? "Габариты" : "Dimensions"}
              value={data.dimensionsMm ? `${data.dimensionsMm.map((value) => Math.round(value * 100) / 100).join(" × ")} ${ru ? "мм" : "mm"}` : (ru ? "Нет измеренного отчёта" : "No measured report")}
            />
          </View>

          <View style={[styles.card, { gap: 4 }]}>
            <Text style={styles.heading}>{ru ? "Доступный экспорт" : "Available exports"}</Text>
            <Text style={styles.muted}>STL · 3MF · GLB · FBX · USDZ</Text>
            <Text style={styles.sectionSubtitle}>
              {ru
                ? "USDZ открывается системным просмотром; STEP и IGES доступны только версиям с точной CAD-геометрией. Паспорт не утверждает их наличие без экспорта."
                : "USDZ opens through the system viewer; STEP and IGES require exact CAD geometry. The passport does not claim they exist before export."}
            </Text>
          </View>

          {!report && (
            <Pressable style={styles.button} onPress={onOpenCheck}>
              <Text style={styles.buttonText}>{ru ? "Открыть проверку модели" : "Open model check"}</Text>
            </Pressable>
          )}
          {report && (
            <View style={[styles.card, { gap: 8 }]}>
              <Text style={styles.heading}>{ru ? "PDF проверки этой версии" : "Integrity PDF for this version"}</Text>
              <Text style={styles.sectionSubtitle}>
                {ru
                  ? "Серверный PDF содержит стабильные ID, измеренные факты и все проверки именно этой immutable-версии. Это не цифровая подпись и не публичный сертификат."
                  : "The server PDF contains stable IDs, measured facts and every check for this immutable version. It is not digitally signed or a public certificate."}
              </Text>
              <Pressable
                accessibilityRole="button"
                disabled={busy}
                style={[styles.button, busy && { opacity: 0.5 }]}
                onPress={onShareIntegrityPdf}
              >
                <Text style={styles.buttonText}>{ru ? "Поделиться PDF проверки" : "Share integrity PDF"}</Text>
              </Pressable>
            </View>
          )}
          <Pressable
            accessibilityRole="button"
            style={[styles.button, styles.buttonPrimary]}
            onPress={() => void Share.share({ message: modelPassportText(data, language) })}
          >
            <Text style={styles.buttonText}>{ru ? "Поделиться паспортом" : "Share passport"}</Text>
          </Pressable>
        </ScrollView>
      )}
    </SheetShell>
  );
}

function PassportRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <View style={{ gap: 2 }}>
      <Text style={styles.sectionSubtitle}>{label}</Text>
      <Text selectable style={mono ? styles.mono : styles.text}>{value}</Text>
    </View>
  );
}
