"use client";

import type { BusinessPlan, Project } from "@physical-ai/contracts";
import Link from "next/link";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { LoadingScreen } from "@/components/LoadingScreen";
import { useSession } from "@/lib/session";

export default function BusinessPage() {
  const { session, ready, client } = useSession();
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [inputs, setInputs] = useState({ margin: 40, machine: 0, labour: 0, packaging: 0 });
  const [plan, setPlan] = useState<BusinessPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ru, setRu] = useState(true);

  useEffect(() => setRu(navigator.language.toLowerCase().startsWith("ru")), []);
  useEffect(() => {
    if (!client || !session) return;
    void client.listProjects(session.workspaceId).then(setProjects).catch((reason) => setError(String(reason)));
  }, [client, session]);
  const candidates = useMemo(() => projects.filter((project) => project.head_version_id), [projects]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!client || !session || selected.length === 0) return;
    setBusy(true);
    setError(null);
    setPlan(null);
    try {
      setPlan(await client.createBusinessPlan({
        workspace_id: session.workspaceId,
        version_ids: selected,
        target_margin_pct: inputs.margin,
        machine_rate_per_hour: inputs.machine,
        labour_per_unit: inputs.labour,
        packaging_per_unit: inputs.packaging,
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  if (!ready) return <LoadingScreen />;
  if (!session) return <div className="card">{ru ? "Войдите в аккаунт." : "Sign in."}</div>;
  return (
    <div className="stack">
      <header className="card stack">
        <h1>{ru ? "Создать линейку товаров" : "Build a product line"}</h1>
        <p className="muted">
          {ru
            ? "Только измеренные данные Print Analysis: материал, время, себестоимость и ваши накладные расходы. Это не прогноз спроса или продаж."
            : "Measured Print Analysis data only: material, time, cost and your overhead. This is not a demand or sales forecast."}
        </p>
      </header>
      <form className="card stack" onSubmit={submit}>
        <strong>{ru ? "1. Модели линейки" : "1. Product-line models"}</strong>
        {candidates.map((project) => (
          <label className="row" key={project.id}>
            <input
              type="checkbox"
              checked={selected.includes(project.head_version_id!)}
              onChange={(event) => setSelected((current) => event.target.checked
                ? [...current, project.head_version_id!]
                : current.filter((id) => id !== project.head_version_id))}
            />
            <span>{project.name}</span>
          </label>
        ))}
        <strong>{ru ? "2. Накладные расходы" : "2. Overhead"}</strong>
        <div className="row" style={{ flexWrap: "wrap" }}>
          {([
            ["margin", ru ? "Целевая маржа, %" : "Target margin, %"],
            ["machine", ru ? "Ставка станка/час" : "Machine/hour"],
            ["labour", ru ? "Труд на единицу" : "Labour/unit"],
            ["packaging", ru ? "Упаковка на единицу" : "Packaging/unit"],
          ] as const).map(([key, label]) => (
            <label className="stack" key={key} style={{ gap: 5 }}>
              <span>{label}</span>
              <input
                className="input mono"
                type="number"
                min="0"
                max={key === "margin" ? 80 : 10000}
                step="0.01"
                value={inputs[key]}
                onChange={(event) => setInputs({ ...inputs, [key]: Number(event.target.value) })}
              />
            </label>
          ))}
        </div>
        <button className="btn primary" type="submit" disabled={busy || selected.length === 0}>
          {busy ? (ru ? "Считаем…" : "Calculating…") : (ru ? "Собрать план" : "Build plan")}
        </button>
        {error && <div className="error">{error}</div>}
      </form>
      {plan && (
        <section className="stack">
          <h2>{ru ? "Линейка и карточки" : "Product line and cards"}</h2>
          <div className="grid projects">
            {plan.products.map((product) => (
              <article className="card stack" key={product.version_id}>
                <strong>{product.title}</strong>
                <span className="muted">{product.description}</span>
                <span>{product.mass_g.toFixed(1)} g · {product.print_time_min.toFixed(0)} min</span>
                <span>{ru ? "Себестоимость" : "Unit cost"}: {product.unit_cost} {product.currency}</span>
                <strong>{ru ? "Расчётная цена" : "Calculated price"}: {product.recommended_price} {product.currency}</strong>
                {!product.render_ready && <span className="status-yellow">{ru ? "Нужен ISO-рендер перед публикацией" : "Generate an ISO render before publishing"}</span>}
                <Link className="btn" href={`/projects/${product.project_id}`}>{ru ? "Открыть модель" : "Open model"}</Link>
              </article>
            ))}
          </div>
          <p className="muted">{ru ? "Цена рассчитана по целевой марже; спрос не заявляется." : "Price follows the target margin; no demand is claimed."}</p>
        </section>
      )}
    </div>
  );
}
