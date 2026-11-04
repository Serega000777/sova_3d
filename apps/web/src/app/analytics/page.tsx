"use client";

import {
  ApiError,
  type IntegrityStatus,
  type Project,
  type WorkspaceVersionActivityItem,
  parseIntegrityReport,
  relativeTime,
} from "@physical-ai/contracts";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { LoadingScreen } from "@/components/LoadingScreen";
import {
  buildProjectAnalytics,
  buildProjectIntegrityAnalytics,
  projectAnalyticsReport,
} from "@/lib/project-analytics";
import { useSession } from "@/lib/session";

function formatAssetBytes(bytes: number, language: "ru" | "en"): string {
  if (bytes < 1024) return `${bytes} ${language === "ru" ? "Б" : "B"}`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} ${language === "ru" ? "КБ" : "KB"}`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} ${language === "ru" ? "МБ" : "MB"}`;
}

function ordinaryModelCheckStatus(value: unknown): IntegrityStatus | null {
  const report = parseIntegrityReport(value);
  return report
    && report.targetFormat === "glb"
    && report.output.format === "glb"
    && report.printableGate === false
    ? report.status
    : null;
}

export default function WorkspaceAnalyticsPage() {
  const { session, ready, client } = useSession();
  const language: "ru" | "en" =
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru")
      ? "ru"
      : "en";
  const ru = language === "ru";
  const [projects, setProjects] = useState<Project[]>([]);
  const [integrityByVersion, setIntegrityByVersion] = useState<Map<string, IntegrityStatus>>(new Map());
  const [integrityLoaded, setIntegrityLoaded] = useState(false);
  const [integrityError, setIntegrityError] = useState<string | null>(null);
  const [activity, setActivity] = useState<WorkspaceVersionActivityItem[]>([]);
  const [activityLoaded, setActivityLoaded] = useState(false);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadRevision = useRef(0);
  const analytics = useMemo(() => buildProjectAnalytics(projects, Date.now()), [projects]);
  const integrity = useMemo(
    () => buildProjectIntegrityAnalytics(projects, integrityByVersion),
    [integrityByVersion, projects],
  );
  const peak = Math.max(1, ...analytics.activity.map((item) => item.updatedProjects));

  const load = useCallback(async () => {
    if (!client || !session) return;
    const request = ++loadRevision.current;
    const workspaceId = session.workspaceId;
    setRefreshing(true);
    setError(null);
    try {
      const nextProjects = await client.listProjects(workspaceId);
      if (loadRevision.current !== request) return;
      setProjects(nextProjects);
      await Promise.all([
        client.listWorkspaceVersionActivity(workspaceId, 30)
          .then((items) => {
            if (loadRevision.current !== request) return;
            setActivity(items);
            setActivityLoaded(true);
            setActivityError(null);
          })
          .catch((reason: unknown) => {
            if (loadRevision.current !== request) return;
            setActivity([]);
            setActivityLoaded(false);
            setActivityError(reason instanceof Error ? reason.message : String(reason));
          }),
        Promise.all(nextProjects.flatMap((project) => project.head_version_id ? [project.head_version_id] : []).map(async (versionId) => {
          try {
            const record = await client.getLatestIntegrityReport(versionId);
            const status = ordinaryModelCheckStatus(record.report);
            if (!status) throw new Error(`Invalid integrity report for version ${versionId}`);
            return [versionId, status] as const;
          } catch (reason) {
            if (reason instanceof ApiError && reason.status === 404) return [versionId, null] as const;
            throw reason;
          }
        }))
          .then((reports) => {
            if (loadRevision.current !== request) return;
            setIntegrityByVersion(new Map(reports.flatMap(([versionId, status]) => (
              status ? [[versionId, status] as const] : []
            ))));
            setIntegrityLoaded(true);
            setIntegrityError(null);
          })
          .catch((reason: unknown) => {
            if (loadRevision.current !== request) return;
            setIntegrityByVersion(new Map());
            setIntegrityLoaded(false);
            setIntegrityError(reason instanceof Error ? reason.message : String(reason));
          }),
      ]);
    } catch (reason) {
      if (loadRevision.current === request) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      if (loadRevision.current === request) {
        setLoaded(true);
        setRefreshing(false);
      }
    }
  }, [client, session]);

  useEffect(() => {
    setLoaded(false);
    setProjects([]);
    setIntegrityByVersion(new Map());
    setIntegrityLoaded(false);
    setIntegrityError(null);
    setActivity([]);
    setActivityLoaded(false);
    setActivityError(null);
    void load();
    return () => { loadRevision.current += 1; };
  }, [load]);

  function downloadSnapshot() {
    const snapshot = Date.now();
    const content = projectAnalyticsReport(analytics, snapshot, integrityLoaded ? integrity : undefined);
    const url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `sova-workspace-analytics-${new Date(snapshot).toISOString().slice(0, 10)}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (!ready) return <LoadingScreen />;
  if (!session) {
    return <div className="empty-stage"><Link className="btn primary" href="/login">{ru ? "Войти" : "Sign in"}</Link></div>;
  }
  if (!loaded && refreshing) return <LoadingScreen />;

  return (
    <div className="stack" style={{ maxWidth: 960 }}>
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: 0 }}>{ru ? "Аналитика проектов" : "Project analytics"}</h1>
          <span className="muted">{ru ? "Канонические факты выбранного workspace · 30 дней" : "Canonical facts for the selected workspace · 30 days"}</span>
        </div>
        <div className="row">
          <button className="btn" type="button" disabled={refreshing} onClick={() => void load()}>{ru ? "Обновить" : "Refresh"}</button>
          <button className="btn primary" type="button" disabled={!loaded || Boolean(error)} onClick={downloadSnapshot}>{ru ? "Скачать снимок" : "Download snapshot"}</button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 12 }}>
        <div className="card stack"><strong>{analytics.totalProjects}</strong><span className="muted">{ru ? "всего проектов" : "projects total"}</span></div>
        <div className="card stack"><strong>{analytics.modelsCreated}</strong><span className="muted">{ru ? "с текущей моделью" : "with a current model"}</span></div>
        <div className="card stack"><strong>{analytics.drafts}</strong><span className="muted">{ru ? "черновиков без модели" : "drafts without a model"}</span></div>
        <div className="card stack"><strong>{analytics.updatedInWindow}</strong><span className="muted">{ru ? "обновлялись за 30 дней" : "updated in 30 days"}</span></div>
      </div>

      <section className="card stack">
        <strong>{ru ? "Проверки текущих версий" : "Current-version checks"}</strong>
        {integrityLoaded ? (
          <>
            <span className="muted">{ru ? "Только последние сохранённые ordinary GLB integrity-отчёты точных head-версий." : "Only the latest persisted ordinary GLB integrity reports for exact head versions."}</span>
            <div className="row" style={{ flexWrap: "wrap" }}>
              <span className="chip">{ru ? "Проверено" : "Checked"}: {integrity.checked}/{integrity.modelHeads}</span>
              <span className="chip">pass: {integrity.passed}</span>
              <span className="chip">warn: {integrity.warnings}</span>
              <span className="chip">fail: {integrity.failed}</span>
              <span className="chip">{ru ? "без отчёта" : "no report"}: {integrity.notChecked}</span>
            </div>
            <span className="muted">{ru ? "Это количество отчётов, не процент качества и не статус завершения." : "These are report counts, not a quality percentage or completion status."}</span>
          </>
        ) : integrityError ? <div className="error">{integrityError}</div> : null}
      </section>

      <section className="card stack">
        <strong>{ru ? "Активность проектов за 30 дней" : "Project activity over 30 days"}</strong>
        <span className="muted">{ru ? "Число проектов по дате последнего серверного обновления." : "Project count by the last server update date."}</span>
        <div className="row" role="img" aria-label={ru ? "График обновлений проектов за 30 дней" : "30-day project update chart"} style={{ height: 140, alignItems: "flex-end", gap: 3 }}>
          {analytics.activity.map((item) => (
            <span
              key={item.day}
              title={`${item.day}: ${item.updatedProjects}`}
              style={{
                flex: 1,
                minWidth: 2,
                height: item.updatedProjects === 0 ? 2 : Math.max(10, (item.updatedProjects / peak) * 132),
                borderRadius: 3,
                background: item.updatedProjects === 0 ? "var(--border)" : "var(--accent)",
              }}
            />
          ))}
        </div>
        <span className="muted">{ru ? "Это активность проектов, а не число созданных версий." : "This is project activity, not a created-version count."}</span>
      </section>

      <section className="card stack">
        <strong>{ru ? "Последние immutable-версии" : "Latest immutable versions"}</strong>
        {activityError && <div className="error">{activityError}</div>}
        {activityLoaded && activity.length === 0 && <span className="muted">{ru ? "Финализированных версий пока нет." : "No finalized versions yet."}</span>}
        <ul className="list">
          {activity.map((item) => (
            <li key={item.version_id} className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
              <span><Link href={`/projects/${item.project_id}`}><strong>{item.project_name}</strong></Link> <span className="muted">· v{item.sequence_no}{item.label ? ` · ${item.label}` : ""}</span></span>
              <span className="muted">{item.creator_name ?? (ru ? "Система" : "System")} · {formatAssetBytes(item.total_asset_bytes, language)} · {relativeTime(item.created_at, Date.now(), language)}</span>
            </li>
          ))}
        </ul>
      </section>

      {analytics.mostRecent ? (
        <Link className="card stack" href={`/projects/${analytics.mostRecent.id}`}>
          <strong>{ru ? "Последний активный проект" : "Most recently active project"}</strong>
          <span>{analytics.mostRecent.name}</span>
          <span className="muted">{relativeTime(analytics.mostRecent.updated_at ?? analytics.mostRecent.created_at, Date.now(), language)}</span>
        </Link>
      ) : loaded && !error ? <div className="card muted">{ru ? "Создайте первый проект — здесь появится измеримая активность." : "Create the first project to see measured activity here."}</div> : null}

      <div className="card stack" style={{ borderColor: "var(--warning, #f59e0b)" }}>
        <strong>{ru ? "Граница данных" : "Data boundary"}</strong>
        <span className="muted">{ru ? "API не хранит статус «завершён». Экран не показывает выдуманный процент готовности или успешных проверок." : "The API has no completed-project status. This page does not invent readiness or pass percentages."}</span>
      </div>
    </div>
  );
}
