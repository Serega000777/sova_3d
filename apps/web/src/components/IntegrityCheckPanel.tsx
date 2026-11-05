"use client";

import {
  ApiError,
  type IntegrityReport,
  type PhysicalAiClient,
  type ProjectSummary,
  type Version,
  type VersionHistoryItem,
} from "@physical-ai/contracts";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { ModelPassportCard } from "@/components/ModelPassportCard";

import {
  MODEL_CHECK_GROUPS,
  modelCheckGroupStatus,
  verifiedModelCheckJob,
  verifiedPersistedModelCheck,
  type ModelCheckGroupStatus,
} from "@/lib/model-check";

type Props = {
  client: PhysicalAiClient;
  versionId: string;
  project: ProjectSummary;
  version: Version;
  history: VersionHistoryItem | null;
  canRun: boolean;
  language: "ru" | "en";
  verificationLinksCard?: ReactNode;
};

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function tone(status: ModelCheckGroupStatus): string {
  return status === "pass"
    ? "var(--success, #4ade80)"
    : status === "fail"
      ? "var(--danger, #fb7185)"
      : "var(--warning, #fbbf24)";
}

export function IntegrityCheckPanel({
  client,
  versionId,
  project,
  version,
  history,
  canRun,
  language,
  verificationLinksCard,
}: Props) {
  const ru = language === "ru";
  const revision = useRef(0);
  const [report, setReport] = useState<IntegrityReport | null>(null);
  const [reportVersionId, setReportVersionId] = useState(versionId);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const request = ++revision.current;
    setReportVersionId(versionId);
    setReport(null);
    setCheckedAt(null);
    setError(null);
    setProgress(0);
    setRunning(false);
    setLoading(true);
    void client
      .getLatestIntegrityReport(versionId)
      .then((record) => {
        if (revision.current !== request) return;
        const parsed = verifiedPersistedModelCheck(record);
        if (!parsed) throw new Error(ru ? "Сохранённый отчёт повреждён." : "The persisted report is invalid.");
        setReportVersionId(versionId);
        setReport(parsed);
        setCheckedAt(record.checked_at);
      })
      .catch((reason: unknown) => {
        if (revision.current !== request) return;
        if (!(reason instanceof ApiError) || reason.status !== 404) setError(message(reason));
      })
      .finally(() => {
        if (revision.current === request) setLoading(false);
      });
    return () => {
      revision.current += 1;
    };
  }, [client, versionId, ru]);

  // A report kept by React for the previous render must never appear under a newly selected version.
  const visibleReport = reportVersionId === versionId ? report : null;
  const visibleLoading = reportVersionId === versionId ? loading : true;
  const visibleRunning = reportVersionId === versionId ? running : false;

  const groups = useMemo(() => visibleReport ? {
    geometry: modelCheckGroupStatus(visibleReport, MODEL_CHECK_GROUPS.geometry),
    scene: modelCheckGroupStatus(visibleReport, MODEL_CHECK_GROUPS.scene),
    appearance: modelCheckGroupStatus(visibleReport, MODEL_CHECK_GROUPS.appearance),
    scale: modelCheckGroupStatus(visibleReport, MODEL_CHECK_GROUPS.scale),
  } : null, [visibleReport]);

  async function runCheck() {
    const request = ++revision.current;
    setRunning(true);
    setLoading(false);
    setProgress(0);
    setError(null);
    try {
      const accepted = await client.exportModel(versionId, {
        format: "glb",
        printable: false,
        game: null,
      });
      const job = await client.waitForJob(accepted.job_id, {
        timeoutMs: 8 * 60_000,
        onProgress: (current) => {
          if (revision.current === request) setProgress(Math.max(0, Math.min(100, current.progress ?? 0)));
        },
      });
      if (revision.current !== request) return;
      const terminalReport = verifiedModelCheckJob(job, versionId);
      if (!terminalReport) {
        const failure = job.error as { message?: string } | null;
        throw new Error(failure?.message ?? (ru ? "Job не вернул проверяемый отчёт." : "The job returned no verifiable report."));
      }
      const persisted = await client.getLatestIntegrityReport(versionId);
      if (revision.current !== request) return;
      const savedReport = verifiedPersistedModelCheck(persisted, accepted.job_id);
      if (!savedReport) {
        throw new Error(ru ? "Сохранённый отчёт не совпал с завершённой проверкой." : "The persisted report did not match the completed check.");
      }
      setReportVersionId(versionId);
      setReport(savedReport);
      setCheckedAt(persisted.checked_at);
      setProgress(100);
    } catch (reason) {
      if (revision.current === request) setError(message(reason));
    } finally {
      if (revision.current === request) setRunning(false);
    }
  }

  async function downloadPdf() {
    setError(null);
    try {
      const blob = await client.downloadIntegrityReport(versionId);
      if (blob.size <= 0 || (blob.type && blob.type !== "application/pdf")) {
        throw new Error(ru ? "Сервер не вернул PDF-отчёт." : "The server did not return a PDF report.");
      }
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `sova-integrity-${versionId}.pdf`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (reason) {
      setError(message(reason));
    }
  }

  const headlineStatus = !visibleReport || !groups
    ? "unknown"
    : visibleReport.status === "fail"
      ? "fail"
      : visibleReport.status === "warn" || groups.appearance === "unknown"
        ? "warn"
        : "pass";

  const rows = visibleReport && groups ? [
    {
      key: "geometry",
      label: ru ? "Геометрия" : "Geometry",
      status: groups.geometry,
      detail: visibleReport.output.faces === null
        ? (ru ? "Проверена целостность преобразования" : "Conversion integrity checked")
        : `${visibleReport.output.faces.toLocaleString()} ${ru ? "треугольников" : "triangles"}${visibleReport.output.watertight === null ? "" : visibleReport.output.watertight ? (ru ? " · замкнута" : " · watertight") : (ru ? " · есть открытые края" : " · open edges")}`,
    },
    {
      key: "scene",
      label: ru ? "Структура сцены" : "Scene structure",
      status: groups.scene,
      detail: groups.scene === "unknown"
        ? (ru ? "Источник не содержит проверяемой сцены" : "The source has no verifiable scene")
        : `${ru ? "Узлов" : "Nodes"}: ${visibleReport.output.nodeCount ?? 0} · mesh: ${visibleReport.output.meshCount ?? 0} · ${ru ? "анимаций" : "animations"}: ${visibleReport.output.animationCount ?? 0}`,
    },
    {
      key: "appearance",
      label: ru ? "Материалы и текстуры" : "Materials and textures",
      status: groups.appearance,
      detail: groups.appearance === "unknown"
        ? (ru ? "Формат источника не содержит проверяемых данных" : "The source format has no verifiable appearance data")
        : `${ru ? "Материалов" : "Materials"}: ${visibleReport.output.materialCount ?? 0} · ${ru ? "текстур" : "textures"}: ${visibleReport.output.textureCount ?? 0}`,
    },
    {
      key: "scale",
      label: ru ? "Масштаб" : "Scale",
      status: groups.scale,
      detail: visibleReport.output.bboxSizeMm
        ? `${visibleReport.output.bboxSizeMm.map((value) => Math.round(value * 100) / 100).join(" × ")} ${ru ? "мм" : "mm"}`
        : (ru ? "Габариты недоступны" : "Dimensions unavailable"),
    },
  ] : [];

  return (
    <div className="stack" data-testid="integrity-check-panel" data-version-id={versionId}>
      <ModelPassportCard
        project={project}
        version={version}
        history={history}
        report={visibleReport}
        loading={visibleLoading}
        language={language}
        onDownloadPdf={() => void downloadPdf()}
        onOpenVerificationLinks={verificationLinksCard ? () => document.getElementById("model-verification-links")?.scrollIntoView({ behavior: "smooth", block: "start" }) : undefined}
      />
      <span className="muted" style={{ fontSize: 12 }}>
        {ru
          ? "Сервер повторно собирает обычный GLB и сверяет геометрию, сцену, материалы, текстуры и единицы. Исходная версия не изменяется."
          : "The server rebuilds an ordinary GLB and compares geometry, scene, materials, textures and units. The source version is not changed."}
      </span>
      <span className="muted" style={{ fontSize: 12 }}>
        {ru
          ? "Это проверка целостности преобразования, а не расчёт прочности, цифровая подпись или нормативная сертификация."
          : "This checks conversion integrity; it is not structural analysis, a digital signature, or regulatory certification."}
      </span>
      {visibleLoading && <span className="muted">{ru ? "Загружаем последний отчёт…" : "Loading the latest report…"}</span>}
      {visibleRunning && (
        <div className="stack" aria-label={ru ? "Ход серверной проверки модели" : "Server model-check progress"}>
          <div className="row"><span>{ru ? "Проверяем модель" : "Checking model"}</span><span className="spacer" /><span>{progress}%</span></div>
          <progress aria-label={ru ? "Прогресс проверки" : "Check progress"} value={progress} max={100} style={{ width: "100%" }} />
          <span className="muted" style={{ fontSize: 12 }}>{ru ? "Процент сообщает серверный job." : "Progress is reported by the server job."}</span>
        </div>
      )}
      {visibleReport && groups ? (
        <div className="stack">
          <strong style={{ color: tone(headlineStatus) }}>
            {headlineStatus === "fail"
              ? (ru ? "Найдены ошибки" : "Issues found")
              : headlineStatus === "warn"
                ? (ru ? "Готово с замечаниями" : "Ready with notes")
                : (ru ? "Проверка пройдена" : "Check passed")}
          </strong>
          {checkedAt && <span className="muted" style={{ fontSize: 12 }}>{ru ? "Проверено" : "Checked"}: {new Date(checkedAt).toLocaleString(ru ? "ru-RU" : "en-US")}</span>}
          {rows.map((row) => (
            <div className="row" key={row.key} style={{ alignItems: "flex-start" }}>
              <strong style={{ color: tone(row.status), minWidth: 20 }}>{row.status === "pass" ? "✓" : row.status === "fail" ? "!" : "?"}</strong>
              <div className="stack" style={{ gap: 2 }}><span>{row.label}</span><span className="muted" style={{ fontSize: 12 }}>{row.detail}</span></div>
            </div>
          ))}
          {visibleReport.checks.filter((check) => check.status !== "pass").map((check) => (
            <span key={check.id} style={{ color: tone(check.status) }}>• {check.message}</span>
          ))}
          <button className="btn" type="button" onClick={() => void downloadPdf()} disabled={visibleRunning}>
            {ru ? "Скачать PDF-отчёт" : "Download PDF report"}
          </button>
        </div>
      ) : !visibleLoading && !visibleRunning ? (
        <span className="muted">{ru ? "Эта версия ещё не проверялась." : "This version has not been checked yet."}</span>
      ) : null}
      {error && <span className="error" role="alert">{error}</span>}
      {canRun ? (
        <button className="btn primary" type="button" onClick={() => void runCheck()} disabled={visibleRunning || visibleLoading}>
          {visibleRunning ? (ru ? "Проверяем…" : "Checking…") : visibleReport ? (ru ? "Проверить ещё раз" : "Check again") : (ru ? "Проверить модель" : "Check model")}
        </button>
      ) : (
        <span className="muted" style={{ fontSize: 12 }}>{ru ? "Запуск доступен редактору; последний сохранённый отчёт доступен для просмотра." : "Editors can run the check; the latest persisted report remains viewable."}</span>
      )}
      {visibleReport && verificationLinksCard}
    </div>
  );
}
