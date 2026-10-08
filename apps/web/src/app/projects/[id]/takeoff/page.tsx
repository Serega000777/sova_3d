"use client";

import type { ConstructionTakeoff, ProjectSummary } from "@physical-ai/contracts";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { LoadingScreen } from "@/components/LoadingScreen";
import { useSession } from "@/lib/session";

const LABELS: Record<string, { ru: string; en: string }> = {
  footprint_area: { ru: "Площадь пятна", en: "Footprint area" },
  total_floor_area: { ru: "Общая площадь этажей", en: "Total floor area" },
  plan_wall_length: { ru: "Длина стен по осям", en: "Plan wall length" },
  gross_wall_area: { ru: "Площадь стен до проёмов", en: "Gross wall area" },
  gross_wall_volume: { ru: "Объём стен по осевой методике", en: "Gross wall volume" },
  door_count: { ru: "Дверные проёмы", en: "Door openings" },
  window_count: { ru: "Оконные проёмы", en: "Window openings" },
};

const UNITS = { m: "м", m2: "м²", m3: "м³", count: "шт." } as const;

export default function ConstructionTakeoffPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { session, ready, client } = useSession();
  const language: "ru" | "en" =
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru")
      ? "ru"
      : "en";
  const ru = language === "ru";
  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [takeoff, setTakeoff] = useState<ConstructionTakeoff | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client) return;
    let active = true;
    void Promise.all([
      client.getProject(projectId),
      client.getConstructionTakeoff(projectId),
    ])
      .then(([nextProject, nextTakeoff]) => {
        if (!active) return;
        setProject(nextProject);
        setTakeoff(nextTakeoff);
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      active = false;
    };
  }, [client, projectId]);

  if (!ready) return <LoadingScreen />;
  if (!session) {
    return (
      <div className="card">
        {ru ? "Войдите, чтобы открыть ведомость проекта." : "Sign in to open the project takeoff."}
      </div>
    );
  }

  return (
    <main className="modeling-home takeoff-page">
      <header className="modeling-hero takeoff-hero">
        <div>
          <span className="eyebrow">{ru ? "ВЕДОМОСТЬ ОБЪЁМОВ" : "QUANTITY TAKEOFF"}</span>
          <h1>{project?.name ?? (ru ? "Проект дома" : "House project")}</h1>
          <p>
            {ru
              ? "Измеримые количества из неизменяемой версии 2D-плана. Цены поставщиков и конструктивные нормы сюда не подставляются."
              : "Measurable quantities from the immutable 2D-plan version. Supplier prices and structural norms are not inserted."}
          </p>
        </div>
        <div className="row">
          <Link className="btn" href={`/projects/${projectId}`}>
            {ru ? "← В Studio" : "← Studio"}
          </Link>
          <Link className="btn primary" href={`/plan?project_id=${projectId}`}>
            {ru ? "Открыть 2D-план" : "Open 2D plan"}
          </Link>
        </div>
      </header>

      {error && <div className="error" role="alert">{error}</div>}
      {!takeoff && !error && <div className="card">{ru ? "Считаем…" : "Calculating…"}</div>}
      {takeoff && (
        <>
          <section className="takeoff-meta card">
            <strong>{ru ? `${takeoff.floors} эт.` : `${takeoff.floors} floor(s)`}</strong>
            <span className="muted">
              {takeoff.floor_height_mm
                ? `${ru ? "высота этажа" : "floor height"}: ${takeoff.floor_height_mm.toLocaleString(language)} ${ru ? "мм" : "mm"}`
                : ru ? "высота стен не указана" : "wall height unavailable"}
            </span>
            <span className="chip">{ru ? "без цен" : "unpriced"}</span>
          </section>

          <section className="takeoff-grid" aria-label={ru ? "Количество работ" : "Measured quantities"}>
            {takeoff.quantities.map((line) => (
              <article className="card takeoff-item" key={line.code}>
                <span className="muted">{LABELS[line.code]?.[language] ?? line.code}</span>
                <strong>
                  {line.quantity.toLocaleString(language, { maximumFractionDigits: 3 })} {UNITS[line.unit]}
                </strong>
                <small>{line.basis}</small>
              </article>
            ))}
          </section>

          <section className="takeoff-notes">
            <article className="card">
              <h2>{ru ? "Допущения" : "Assumptions"}</h2>
              <ul>{takeoff.assumptions.map((item) => <li key={item}>{item}</li>)}</ul>
            </article>
            <article className="card">
              <h2>{ru ? "Ограничения" : "Limitations"}</h2>
              <ul>{takeoff.warnings.map((item) => <li key={item}>{item}</li>)}</ul>
            </article>
          </section>
        </>
      )}
    </main>
  );
}
