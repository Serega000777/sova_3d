"use client";

import type {
  FacadeCompatibility,
  FacadeFitAccepted,
  FitTestReport,
  PhysicalAiClient,
  Project,
} from "@physical-ai/contracts";
import { useState } from "react";

type Language = "ru" | "en";

export interface MarketplaceFacadePlacementProps {
  client: PhysicalAiClient;
  orderId: string;
  targetProject: Project;
  compatibility: FacadeCompatibility;
  language: Language;
  disabled: boolean;
  onCreated: (versionId: string) => void;
}

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
  targetProject,
  compatibility,
  language,
  disabled,
  onCreated,
}: MarketplaceFacadePlacementProps) {
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [fitTestId, setFitTestId] = useState<string | null>(null);
  const [report, setReport] = useState<FitTestReport | null>(null);
  const [limitations, setLimitations] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const ru = language === "ru";

  async function run(openingId: string, sourceVersionId: string) {
    if (!targetProject.head_version_id) return;
    const key = `${openingId}:${sourceVersionId}`;
    setBusyKey(key);
    setError(null);
    setFitTestId(null);
    setReport(null);
    try {
      const accepted = await client.startMarketplaceFacadeFit(orderId, {
        target_project_id: targetProject.id,
        opening_id: openingId,
        source_version_id: sourceVersionId,
        language,
      });
      if (!acceptedMatches(
        accepted,
        targetProject.head_version_id,
        openingId,
        sourceVersionId,
      )) {
        throw new Error(ru
          ? "Сервер вернул проверку не для выбранного проёма или версии фасада."
          : "The server returned a fit test for a different opening or facade version.");
      }
      const job = await client.waitForJob(accepted.job_id, { timeoutMs: 8 * 60_000 });
      if (job.status !== "succeeded") {
        throw new Error((job.error as { message?: string } | null)?.message
          ?? (ru ? "Адресная проверка не выполнена." : "The addressed fit test failed."));
      }
      const result = job.result as {
        fit_test_id?: unknown;
        version_a_id?: unknown;
        report?: FitTestReport;
      } | null;
      if (result?.version_a_id !== targetProject.head_version_id
        || typeof result.fit_test_id !== "string"
        || !result.report?.measured?.b_transform) {
        throw new Error(ru
          ? "Результат не содержит доказанную позу выбранного фасада."
          : "The result has no verified pose for the selected facade.");
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
        ru ? "Адресное размещение фасадного элемента" : "Addressed facade placement",
      );
      onCreated(scene.version_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusyKey(null);
    }
  }

  const verdict = report?.measured.verdict;
  return (
    <div className="card stack">
      <strong>{ru ? "Адресное размещение после покупки" : "Addressed placement after purchase"}</strong>
      <span className="muted">{ru
        ? "Выберите сохранённый opening_id и доставленный модуль. Сервер поставит его на среднюю плоскость проёма и измерит реальные mesh‑коллизии."
        : "Choose a saved opening_id and delivered module. The server centres it on the opening plane and measures real mesh collisions."}</span>
      <ul className="list">
        {compatibility.openings.flatMap((opening) => opening.matches.map((match) => {
          const key = `${opening.opening_id}:${match.version_id}`;
          return (
            <li key={key} className="row" style={{ justifyContent: "space-between" }}>
              <span>{opening.opening_id} · {opening.side} · {opening.width_mm.toFixed(0)} × {opening.height_mm.toFixed(0)} mm · {match.label}</span>
              <button
                className="btn"
                type="button"
                disabled={disabled || busyKey !== null}
                onClick={() => void run(opening.opening_id, match.version_id)}
              >
                {busyKey === key
                  ? (ru ? "Проверяю…" : "Checking…")
                  : (ru ? "Проверить этот проём" : "Check this opening")}
              </button>
            </li>
          );
        }))}
      </ul>
      {report && (
        <div className="stack" style={{ gap: 6 }}>
          <span className={`chip ${verdict === "collides" ? "status-red" : verdict === "apart" || verdict === "loose" ? "status-yellow" : "status-green"}`}>
            {ru ? `Результат: ${verdict}` : `Result: ${verdict}`}
          </span>
          <span className="muted">{report.advice.summary}</span>
          <span className="mono">
            {ru ? "Проникновение" : "Penetration"}: {report.measured.max_penetration_mm.toFixed(3)} mm
            {report.measured.min_clearance_mm !== null
              ? ` · ${ru ? "зазор" : "clearance"}: ${report.measured.min_clearance_mm.toFixed(3)} mm`
              : ""}
          </span>
          {limitations.map((item) => <span className="muted" key={item}>• {item}</span>)}
          {fitTestId && verdict !== "collides" && (
            <button className="btn primary" type="button" disabled={busyKey !== null} onClick={() => void save()}>
              {busyKey === "save"
                ? (ru ? "Сохраняю…" : "Saving…")
                : (ru ? "Сохранить immutable‑размещение" : "Save immutable placement")}
            </button>
          )}
        </div>
      )}
      {error && <span className="error">{error}</span>}
    </div>
  );
}
