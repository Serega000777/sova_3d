"use client";

import {
  ApiError,
  relativeTime,
  type PhysicalAiClient,
  type ProjectSummary,
  type Version,
} from "@physical-ai/contracts";
import { useEffect, useRef, useState } from "react";

import { verifiedPersistedModelCheck } from "@/lib/model-check";

type CheckState = "not_run" | "passed" | "warning" | "failed" | "unavailable";

type Props = {
  client: PhysicalAiClient;
  project: ProjectSummary;
  version: Version | null;
  versionCount: number;
  previewUrl: string | null;
  language: "ru" | "en";
  onCheck: () => void;
  onComments: () => void;
  onVersions: () => void;
  onExport: () => void;
};

function checkLabel(state: CheckState, ru: boolean): string {
  if (state === "passed") return ru ? "Проверка пройдена" : "Check passed";
  if (state === "warning") return ru ? "Есть замечания проверки" : "Check has notes";
  if (state === "failed") return ru ? "Проверка не пройдена" : "Check failed";
  if (state === "unavailable") return ru ? "Отчёт проверки недоступен" : "Check report unavailable";
  return ru ? "Проверка не запускалась" : "Check has not run";
}

export function ProjectDashboardCard({
  client,
  project,
  version,
  versionCount,
  previewUrl,
  language,
  onCheck,
  onComments,
  onVersions,
  onExport,
}: Props) {
  const ru = language === "ru";
  const revision = useRef(0);
  const [participantCount, setParticipantCount] = useState<number | null>(null);
  const [checkState, setCheckState] = useState<CheckState>("not_run");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const request = ++revision.current;
    setParticipantCount(null);
    setCheckState("not_run");
    setLoading(true);

    void client.listWorkspaceMembers(project.workspace_id)
      .then((members) => {
        if (revision.current === request) setParticipantCount(Math.max(1, members.length));
      })
      .catch(() => undefined);

    if (!version) {
      setLoading(false);
      return () => { revision.current += 1; };
    }
    void client.getLatestIntegrityReport(version.id)
      .then((record) => {
        if (revision.current !== request) return;
        const report = verifiedPersistedModelCheck(record);
        if (!report) {
          setCheckState("unavailable");
          return;
        }
        setCheckState(report.status === "pass" ? "passed" : report.status === "fail" ? "failed" : "warning");
      })
      .catch((reason: unknown) => {
        if (reason instanceof ApiError && reason.status === 404) return;
        if (revision.current === request) setCheckState("unavailable");
      })
      .finally(() => {
        if (revision.current === request) setLoading(false);
      });
    return () => { revision.current += 1; };
  }, [client, project.workspace_id, version]);

  const hasModel = Boolean(version?.assets.some((asset) => asset.role === "model" || asset.role === "preview"));
  const stateClass = checkState === "passed"
    ? "status-green"
    : checkState === "failed"
      ? "status-red"
      : "status-yellow";

  return (
    <div className="stack" data-testid="project-dashboard-card" data-version-id={version?.id ?? "draft"}>
      <div>
        <strong>{ru ? "Панель проекта" : "Project dashboard"}</strong>
        <h3 style={{ margin: "6px 0" }}>{project.name}</h3>
        <span className="muted" style={{ fontSize: 12 }}>
          {ru
            ? "Только подтверждённые данные проекта — без расчётного процента готовности."
            : "Canonical project facts only — no invented readiness percentage."}
        </span>
      </div>
      {previewUrl && (
        <img
          src={previewUrl}
          alt={ru ? `Сохранённое превью проекта ${project.name}` : `Saved preview for ${project.name}`}
          style={{ width: "100%", aspectRatio: "16 / 9", borderRadius: 12, objectFit: "cover" }}
        />
      )}
      <div className="row" style={{ flexWrap: "wrap" }}>
        <span className={`chip ${hasModel ? "status-green" : "status-yellow"}`}>
          {hasModel ? (ru ? "Модель создана" : "Model available") : (ru ? "Черновик без модели" : "Draft without model")}
        </span>
        <span className="chip">
          {versionCount} {ru ? "верс." : versionCount === 1 ? "version" : "versions"}
        </span>
        {participantCount !== null && (
          <span className="chip">
            {participantCount} {ru ? "участн." : participantCount === 1 ? "participant" : "participants"}
          </span>
        )}
      </div>
      <span className={stateClass}>
        {loading ? (ru ? "Загружаем последнюю проверку…" : "Loading latest check…") : checkLabel(checkState, ru)}
      </span>
      <span className="muted" style={{ fontSize: 12 }}>
        {ru ? "Сервер обновлён" : "Server updated"}: {project.updated_at
          ? relativeTime(project.updated_at, Date.now(), language)
          : (ru ? "нет данных" : "unknown")}
      </span>
      <div className="stack" style={{ gap: 8 }}>
        <strong>{ru ? "Следующие действия" : "Next actions"}</strong>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <button className="btn" type="button" onClick={onCheck}>{ru ? "Проверить модель" : "Check model"}</button>
          <button className="btn" type="button" onClick={onComments}>{ru ? "Комментарии" : "Comments"}</button>
          <button className="btn" type="button" onClick={onVersions}>{ru ? "Версии" : "Versions"}</button>
          <button className="btn primary" type="button" onClick={onExport}>{ru ? "Подготовить экспорт" : "Prepare export"}</button>
        </div>
      </div>
    </div>
  );
}
