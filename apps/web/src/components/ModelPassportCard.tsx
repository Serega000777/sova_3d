"use client";

import type {
  IntegrityReport,
  ProjectSummary,
  Version,
  VersionHistoryItem,
} from "@physical-ai/contracts";
import { useEffect, useState } from "react";

export interface ModelPassportData {
  projectName: string;
  projectId: string;
  versionId: string;
  sequenceNo: number;
  author: string;
  createdAt: string;
  storedFileCount: number;
  integrity: "passed" | "warning" | "failed" | "not_checked";
  dimensionsMm: [number, number, number] | null;
}

export function modelPassportData(
  project: ProjectSummary,
  version: Version,
  history: VersionHistoryItem | null,
  report: IntegrityReport | null,
): ModelPassportData {
  return {
    projectName: project.name,
    projectId: project.id,
    versionId: version.id,
    sequenceNo: version.sequence_no,
    author: history?.creator_name ?? (version.created_by ? version.created_by.slice(0, 8) : "System"),
    createdAt: version.created_at,
    storedFileCount: version.assets.length,
    integrity: !report
      ? "not_checked"
      : report.status === "fail"
        ? "failed"
        : report.status === "warn"
          ? "warning"
          : "passed",
    dimensionsMm: report?.output.bboxSizeMm ?? null,
  };
}

function dimensionsText(dimensions: [number, number, number] | null, ru: boolean): string {
  return dimensions
    ? `${dimensions.map((value) => Math.round(value * 100) / 100).join(" × ")} ${ru ? "мм" : "mm"}`
    : (ru ? "не измерены" : "not measured");
}

export function modelPassportText(data: ModelPassportData, language: "ru" | "en"): string {
  const ru = language === "ru";
  const status = {
    passed: ru ? "проверена" : "passed",
    warning: ru ? "с замечаниями" : "warning",
    failed: ru ? "не прошла проверку" : "failed",
    not_checked: ru ? "не проверялась" : "not checked",
  }[data.integrity];
  return [
    ru ? "Паспорт 3D-модели Sova 3D" : "Sova 3D model passport",
    `${ru ? "Проект" : "Project"}: ${data.projectName}`,
    `${ru ? "ID проекта" : "Project ID"}: ${data.projectId}`,
    `${ru ? "Версия" : "Version"}: v${data.sequenceNo} (${data.versionId})`,
    `${ru ? "Автор версии" : "Version author"}: ${data.author}`,
    `${ru ? "Создана" : "Created"}: ${new Date(data.createdAt).toLocaleString(ru ? "ru-RU" : "en-US")}`,
    `${ru ? "Проверка целостности" : "Integrity check"}: ${status}`,
    `${ru ? "Габариты" : "Dimensions"}: ${dimensionsText(data.dimensionsMm, ru)}`,
    `${ru ? "Сохранённых файлов" : "Stored files"}: ${data.storedFileCount}`,
  ].join("\n");
}

export function ModelPassportCard({
  project,
  version,
  history,
  report,
  loading,
  language,
  onDownloadPdf,
  onOpenVerificationLinks,
}: {
  project: ProjectSummary;
  version: Version;
  history: VersionHistoryItem | null;
  report: IntegrityReport | null;
  loading: boolean;
  language: "ru" | "en";
  onDownloadPdf: () => void;
  onOpenVerificationLinks?: () => void;
}) {
  const ru = language === "ru";
  const data = modelPassportData(project, version, history, report);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");

  useEffect(() => setCopyState("idle"), [version.id]);

  async function copyPassport() {
    try {
      await navigator.clipboard.writeText(modelPassportText(data, language));
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
  }

  const status = loading
    ? (ru ? "Загружаем проверку…" : "Loading check…")
    : data.integrity === "passed"
      ? (ru ? "Проверена" : "Passed")
      : data.integrity === "warning"
        ? (ru ? "С замечаниями" : "Warning")
        : data.integrity === "failed"
          ? (ru ? "Не прошла проверку" : "Failed")
          : (ru ? "Не проверялась" : "Not checked");

  return (
    <section className="stack" data-testid="model-passport" data-version-id={version.id}>
      <div className="row">
        <strong>{ru ? "Паспорт 3D-модели" : "3D model passport"}</strong>
        <span className="spacer" />
        <span className="chip">{status}</span>
      </div>
      <span className="muted" style={{ fontSize: 12 }}>
        {ru ? "Канонические данные выбранной неизменяемой версии." : "Canonical data for the selected immutable version."}
      </span>
      {!loading && !report && (
        <span className="muted" data-testid="passport-not-checked">
          {ru ? "Эта версия ещё не проверялась; паспорт не подменяет проверку зелёным статусом." : "This version has not been checked; the passport does not invent a green status."}
        </span>
      )}
      <div className="stack" style={{ padding: 12, borderRadius: 8, background: "var(--panel-2)" }}>
        <span><strong>{ru ? "Название" : "Name"}:</strong> {data.projectName}</span>
        <span><strong>{ru ? "ID проекта" : "Project ID"}:</strong> <code>{data.projectId}</code></span>
        <span><strong>{ru ? "Версия" : "Version"}:</strong> <code>v{data.sequenceNo} · {data.versionId}</code></span>
        <span><strong>{ru ? "Автор версии" : "Version author"}:</strong> {data.author}</span>
        <span><strong>{ru ? "Создана" : "Created"}:</strong> {new Date(data.createdAt).toLocaleString(ru ? "ru-RU" : "en-US")}</span>
        <span><strong>{ru ? "Сохранённых файлов" : "Stored files"}:</strong> {data.storedFileCount}</span>
        <span><strong>{ru ? "Измеренные габариты" : "Measured dimensions"}:</strong> {dimensionsText(data.dimensionsMm, ru)}</span>
      </div>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <button className="btn primary" type="button" onClick={() => void copyPassport()}>
          {copyState === "copied"
            ? (ru ? "Паспорт скопирован" : "Passport copied")
            : (ru ? "Копировать паспорт как текст" : "Copy passport as text")}
        </button>
        {report && (
          <button className="btn" type="button" onClick={onDownloadPdf}>
            {ru ? "Скачать PDF проверки" : "Download integrity PDF"}
          </button>
        )}
        {report && onOpenVerificationLinks && (
          <button className="btn" type="button" onClick={onOpenVerificationLinks}>
            {ru ? "Публичная ссылка проверки" : "Public verification link"}
          </button>
        )}
      </div>
      {copyState === "error" && <span className="error" role="alert">{ru ? "Не удалось скопировать паспорт." : "Could not copy the passport."}</span>}
    </section>
  );
}
