"use client";

import {
  ApiError,
  type HouseTextProposal,
  type PhysicalAiClient,
  houseTextApplyBody,
  houseTextFootprint,
  houseTextProposalIsExact,
  houseTextRefusal,
  houseTextRows,
} from "@physical-ai/contracts";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

type Language = "ru" | "en";

const EXAMPLES: Record<Language, readonly string[]> = {
  ru: [
    "Создай двухэтажный прямоугольный дом 12 × 8 м, высота этажа 3 м",
    "Построй дом длиной 10 м и шириной 9 м, 1 этаж, высота этажа 280 см",
  ],
  en: [
    "Build a rectangular house 12 m x 8 m, 2 floors, floor height 3 m",
    "Create a house 10 m long, 9 m wide, 1 floor, floor height 2800 mm",
  ],
};

/** Item 41/98: description → server proposal with an exact massing outline → explicit Apply/Cancel → existing house-box job. */
export function HouseTextWizard({
  client,
  workspaceId,
  language,
  onBack,
}: {
  client: PhysicalAiClient;
  workspaceId: string;
  language: Language;
  onBack: () => void;
}) {
  const router = useRouter();
  const ru = language === "ru";
  const [text, setText] = useState("");
  // The exact text the proposal was derived from; Apply re-sends it for server re-parsing.
  const [proposedText, setProposedText] = useState<string | null>(null);
  const [proposal, setProposal] = useState<HouseTextProposal | null>(null);
  const [busy, setBusy] = useState<"propose" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Fail-closed: malformed dimensions or an unsupported shape never render a preview or allow apply.
  const footprint = proposal ? houseTextFootprint(proposal.request) : null;

  function explain(reason: unknown) {
    if (reason instanceof ApiError) return houseTextRefusal(reason.details, reason.message, language);
    return reason instanceof Error ? reason.message : String(reason);
  }

  function edit(value: string) {
    setText(value);
    // Any edit invalidates the shown proposal: nothing stale can be applied.
    setProposal(null);
    setProposedText(null);
    setError(null);
  }

  async function propose(event: FormEvent) {
    event.preventDefault();
    const prompt = text.trim();
    if (!prompt) return;
    setBusy("propose");
    setError(null);
    try {
      const next = await client.proposeHouseFromText({ workspace_id: workspaceId, prompt });
      if (!houseTextProposalIsExact(next, { workspaceId, projectId: null })) {
        throw new Error(ru
          ? "Сервер вернул несогласованное предложение. Получите его заново."
          : "The server returned an inconsistent proposal. Request it again.");
      }
      setProposal(next);
      setProposedText(prompt);
    } catch (reason) {
      setProposal(null);
      setProposedText(null);
      setError(explain(reason));
    } finally {
      setBusy(null);
    }
  }

  async function apply() {
    if (!proposal || proposedText === null || !footprint) return;
    setBusy("apply");
    setError(null);
    try {
      const accepted = await client.applyHouseFromText(
        houseTextApplyBody(proposal, proposedText),
        crypto.randomUUID(),
      );
      const job = await client.waitForJob(accepted.job.job_id, { intervalMs: 1_000 });
      if (job.status !== "succeeded") {
        throw new Error(
          (job.error as { message?: string } | null)?.message
            ?? (ru ? "Дом не построен" : "The house was not built"),
        );
      }
      router.push(`/projects/${accepted.project_id}?goal=house_design`);
    } catch (reason) {
      setError(explain(reason));
      setBusy(null);
    }
  }

  function cancel() {
    setProposal(null);
    setProposedText(null);
    setError(null);
  }

  return (
    <div className="create-studio house-box-wizard house-text-wizard">
      <div className="create-intro">
        <span className="eyebrow">{ru ? "ДОМ ПО ОПИСАНИЮ" : "HOUSE FROM A DESCRIPTION"}</span>
        <h1>{ru ? "Опишите дом" : "Describe the house"}</h1>
        <p>
          {ru
            ? "Укажите размеры с единицами (мм, см или м), высоту этажа и число этажей. Мы покажем, что поняли, и ничего не построим без вашего подтверждения."
            : "Give dimensions with units (mm, cm or m), floor height and number of floors. We show what we understood and build nothing until you confirm."}
        </p>
      </div>
      <form className="house-box-form card" onSubmit={propose}>
        <label>
          <span>{ru ? "Описание дома" : "House description"}</span>
          <textarea
            className="input creation-prompt"
            value={text}
            maxLength={500}
            onChange={(event) => edit(event.target.value)}
            placeholder={EXAMPLES[language][0]}
            disabled={busy === "apply"}
          />
        </label>
        <div className="idea-chips">
          {EXAMPLES[language].map((example) => (
            <button type="button" className="chip" key={example} onClick={() => edit(example)} disabled={busy !== null}>
              {example}
            </button>
          ))}
        </div>
        <p className="muted">
          {ru
            ? "Поддерживаются прямоугольная, Г- и Т-образная массы без лестниц, крыши, окон и комнат — добавьте их позже в редакторе."
            : "Rectangular, L-shaped and T-shaped masses are supported, without stairs, roof, windows or rooms — add those later in the editor."}
        </p>
        {proposal && (
          <section className="card stack house-text-proposal" aria-live="polite">
            <strong>{ru ? "Предложение — проверьте параметры" : "Proposal — check the parameters"}</strong>
            <p>{ru ? proposal.summary_ru : proposal.summary_en}</p>
            {footprint ? (
              <div
                className="house-text-footprint stack"
                aria-label={ru ? "Точное пятно застройки из предложения сервера" : "Exact footprint from the server proposal"}
              >
                <svg
                  className="house-text-footprint-svg"
                  viewBox={`-500 -500 ${proposal.request.length_mm + 1_000} ${proposal.request.width_mm + 1_000}`}
                  role="img"
                  aria-label={ru ? "Схема массы дома — не фасад" : "House massing diagram — not a facade"}
                >
                  <polygon
                    points={footprint.map(([x, y]) => `${x},${y}`).join(" ")}
                    fill="var(--accent-wash-strong)"
                    stroke="var(--accent)"
                    strokeWidth={Math.max(proposal.request.length_mm, proposal.request.width_mm) / 180}
                  />
                </svg>
                <small className="muted">
                  {ru
                    ? `Схема массы (не фотореалистичный фасад) · ${proposal.request.length_mm.toLocaleString("ru")} × ${proposal.request.width_mm.toLocaleString("ru")} мм`
                    : `Massing diagram, not a photoreal facade · ${proposal.request.length_mm.toLocaleString("en")} × ${proposal.request.width_mm.toLocaleString("en")} mm`}
                </small>
              </div>
            ) : (
              <div className="error" role="alert">
                {ru ? "Сервер вернул неподдерживаемое пятно дома." : "The server returned an unsupported house footprint."}
              </div>
            )}
            <table className="house-text-table">
              <thead>
                <tr>
                  <th>{ru ? "Параметр" : "Parameter"}</th>
                  <th>{ru ? "Значение" : "Value"}</th>
                  <th>{ru ? "Из текста" : "From the text"}</th>
                </tr>
              </thead>
              <tbody>
                {houseTextRows(proposal, language).map((row) => (
                  <tr key={row.field}>
                    <td>{row.label}</td>
                    <td><strong>{row.value}</strong></td>
                    <td className="muted">{row.source ?? (ru ? "по умолчанию" : "default")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="house-total">
              {ru ? "Общая высота" : "Total height"}: <strong>{proposal.total_height_mm.toLocaleString(language)} {ru ? "мм" : "mm"}</strong>
              {" · "}
              {ru ? "Площадь пятна" : "Footprint"}: <strong>{proposal.footprint_area_m2.toLocaleString(language)} {ru ? "м²" : "m²"}</strong>
            </p>
            <small className="muted">
              {ru
                ? "Задание ещё не создано, AI не используется. «Применить» создаст новый проект с неизменяемой первой версией."
                : "No job has been created and no AI is used. Apply creates a new project with an immutable first version."}
            </small>
          </section>
        )}
        {error && <div className="error" role="alert">{error}</div>}
        <div className="house-box-actions">
          <button type="button" className="btn" onClick={onBack} disabled={busy !== null}>{ru ? "← Назад" : "← Back"}</button>
          {proposal ? (
            <span className="house-text-confirm">
              <button type="button" className="btn" onClick={cancel} disabled={busy !== null}>{ru ? "Отмена" : "Cancel"}</button>
              <button type="button" className="btn primary" onClick={() => void apply()} disabled={busy !== null || !footprint}>
                {busy === "apply" ? (ru ? "Строим…" : "Building…") : (ru ? "Применить и создать дом" : "Apply and create house")}
              </button>
            </span>
          ) : (
            <button type="submit" className="btn primary" disabled={busy !== null || !text.trim()}>
              {busy === "propose" ? (ru ? "Разбираем…" : "Reading…") : (ru ? "Показать предложение" : "Show proposal")}
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
