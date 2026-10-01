"use client";

import { scanStage } from "@physical-ai/contracts";

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
