"use client";

import type { Job } from "@physical-ai/contracts";
import { scanStage } from "@physical-ai/contracts";
import { useEffect } from "react";

/** Where a scan is on its way from the camera to the project, from its real status. */
const STEPS = {
  ru: ["Съёмка", "Обработка", "Готово", "В проекте"],
  en: ["Capture", "Processing", "Ready", "In project"],
} as const;

export function ScanProgress({ status, language }: { status: string; language: "ru" | "en" }) {
  const current = scanStage(status);
  const failed = status === "failed";
  const labels = STEPS[language];
  return (
    <ol className="scan-progress" aria-label={language === "ru" ? "Этапы скана" : "Scan stages"}>
      {labels.map((label, index) => {
        const state = failed ? (index === 0 ? "done" : index === 1 ? "failed" : "todo") : current === null ? "todo" : index < current ? "done" : index === current ? (current === 3 ? "done" : "current") : "todo";
        return (
          <li key={label} className={state} aria-current={state === "current" ? "step" : undefined}>
            <span className="scan-progress-dot" aria-hidden="true">{state === "done" ? "✓" : state === "failed" ? "!" : ""}</span>
            {label}
          </li>
        );
      })}
    </ol>
  );
}

export function ScanProgressModal({
  open,
  status,
  job,
  frameCount,
  errorMessage,
  syncing,
  pausing,
  language,
  onClose,
  onPause,
}: {
  open: boolean;
  status: string;
  job: Job | null;
  frameCount: number;
  errorMessage?: string;
  syncing: boolean;
  pausing: boolean;
  language: "ru" | "en";
  onClose: () => void;
  onPause: () => void;
}) {
  const ru = language === "ru";
  const currentStatus =
    job?.status === "failed" || job?.status === "canceled" || job?.status === "paused"
      ? job.status
      : job?.status === "succeeded"
        ? "ready"
        : status;
  const progress = Math.max(0, Math.min(job?.progress ?? 0, 100));

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, open]);

  if (!open) return null;
  return (
    <div
      className="guide-backdrop"
      role="presentation"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <section
        className="guide-sheet scan-progress-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="scan-progress-title"
      >
        <button
          type="button"
          className="guide-close"
          onClick={onClose}
          aria-label={ru ? "Закрыть" : "Close"}
        >
          ×
        </button>
        {syncing ? (
          <div className="stack" aria-live="polite">
            <h2 id="scan-progress-title">{ru ? "Обновляем статус…" : "Refreshing status…"}</h2>
            <p className="muted">
              {ru ? "Получаем актуальное состояние задачи с сервера." : "Getting the current job state from the server."}
            </p>
          </div>
        ) : currentStatus === "failed" ? (
          <div className="stack" aria-live="assertive">
            <h2 id="scan-progress-title" className="status-red">
              {ru ? "Обработка не завершена" : "Processing failed"}
            </h2>
            <p className="muted">
              {errorMessage ?? (ru ? "Сервис не смог собрать 3D-модель." : "The service could not build the 3D model.")}
            </p>
            <button type="button" className="btn" onClick={onClose}>
              {ru ? "Закрыть" : "Close"}
            </button>
          </div>
        ) : currentStatus === "canceled" ? (
          <div className="stack" aria-live="polite">
            <h2 id="scan-progress-title" className="status-yellow">
              {ru ? "Обработка отменена" : "Processing canceled"}
            </h2>
            <p className="muted">
              {ru ? "Задача остановлена. Снятые кадры сохранены." : "The job stopped. Captured frames were kept."}
            </p>
            <button type="button" className="btn" onClick={onClose}>
              {ru ? "Закрыть" : "Close"}
            </button>
          </div>
        ) : currentStatus === "ready" || currentStatus === "accepted" ? (
          <div className="stack" aria-live="polite">
            <h2 id="scan-progress-title" className="status-green">
              {ru ? "3D-модель готова" : "3D model ready"}
            </h2>
            <p className="muted">
              {ru ? "Обработка завершена — можно проверить результат." : "Processing is complete — the result is ready to review."}
            </p>
            <button type="button" className="btn primary" onClick={onClose}>
              {ru ? "Посмотреть результат" : "Review result"}
            </button>
          </div>
        ) : currentStatus === "paused" ? (
          <div className="stack" aria-live="polite">
            <h2 id="scan-progress-title" className="status-yellow">
              {ru ? "Обработка приостановлена" : "Processing paused"}
            </h2>
            <p className="muted">
              {ru ? "Продолжить задачу можно на странице скана." : "You can resume the job from the scan page."}
            </p>
            <button type="button" className="btn" onClick={onClose}>
              {ru ? "Закрыть" : "Close"}
            </button>
          </div>
        ) : (
          <div className="stack" aria-live="polite">
            <h2 id="scan-progress-title">{ru ? "Создаём 3D-модель" : "Building the 3D model"}</h2>
            <p className="muted">
              {ru
                ? `Обрабатываем ${frameCount} кадров. Окно можно закрыть — задача продолжится в фоне.`
                : `Processing ${frameCount} frames. You can close this window — the job will keep running.`}
            </p>
            <div className="scan-progress-header">
              <strong>{job?.stage ?? (ru ? "Обработка скана" : "Processing scan")}</strong>
              <strong className="scan-progress-value">{Math.round(progress)}%</strong>
            </div>
            <div
              className="scan-progress-track"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progress)}
            >
              <span style={{ width: `${progress}%` }} />
            </div>
            <ScanProgress status={status} language={language} />
            <div className="row scan-progress-actions">
              <button type="button" className="btn" disabled={pausing} onClick={onPause}>
                {pausing ? (ru ? "Приостанавливаем…" : "Pausing…") : ru ? "Приостановить" : "Pause"}
              </button>
              <button type="button" className="btn primary" onClick={onClose}>
                {ru ? "Скрыть" : "Hide"}
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
