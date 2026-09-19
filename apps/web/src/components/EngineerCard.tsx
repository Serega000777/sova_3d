"use client";

/**
 * Ask the engineer (T-119, F-005): not a chat, an engineer.
 *
 * A question about the model — or about the area outlined on it — comes back as a verdict
 * with the measured numbers, the reasons, a recommendation and, when the fix is a number
 * the kernel understands, a button that applies it as an ordinary edit.
 */
import type { EngineeringAnswer, EngineeringReportBody, Job } from "@physical-ai/contracts";
import { type FormEvent, useState } from "react";

const EXAMPLES = [
  "Эта стенка слишком тонкая?",
  "Will it hold 5 kg?",
  "Какой пластик выбрать для улицы?",
  "Holes for M5 screws",
  "Какой зазор под скользящую посадку?",
];

const MATERIALS = [
  { id: "pla", name: "PLA" },
  { id: "petg", name: "PETG" },
  { id: "abs", name: "ABS" },
  { id: "tpu", name: "TPU" },
  { id: "asa", name: "ASA" },
];

export interface EngineerCardProps {
  disabled: boolean;
  /** The area the question is about, when one is outlined. */
  hasRegion: boolean;
  onAsk: (body: {
    question: string | null;
    purpose: string | null;
    material_id: string;
  }) => Promise<Job | null>;
  onApplyFix: (fix: NonNullable<EngineeringAnswer["fix"]>) => Promise<void>;
  /** F-009: adapt the part for the material chosen in the card (a preview). */
  onAdapt?: (materialId: string) => Promise<void>;
  /** F-007: hollow the part to the material's wall — a preview with the mass before/after. */
  onLighten?: (materialId: string) => Promise<void>;
}

function verdictClass(verdict: EngineeringAnswer["verdict"]): string {
  // "yes" answers "is something wrong?" — so yes is the worrying one
  return verdict === "yes" ? "status-red" : verdict === "no" ? "status-green" : "status-yellow";
}

function AnswerView({
  answer,
  onApplyFix,
  disabled,
}: {
  answer: EngineeringAnswer;
  onApplyFix: EngineerCardProps["onApplyFix"];
  disabled: boolean;
}) {
  const fix = answer.fix;
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div>
        <span className={`chip ${verdictClass(answer.verdict)}`}>{answer.intent}</span>{" "}
        {answer.summary}
      </div>
      {answer.reasons.length > 0 && (
        <ul className="list">
          {answer.reasons.map((reason) => (
            <li key={reason} className="muted">
              {reason}
            </li>
          ))}
        </ul>
      )}
      {answer.recommendation && <div>{answer.recommendation}</div>}
      {fix && (
        <div className="row">
          <button
            type="button"
            className="btn primary"
            disabled={disabled}
            onClick={() => void onApplyFix(fix)}
          >
            Apply: {fix.label}
          </button>
          <span className="muted">
            {fix.operations.length} operation{fix.operations.length === 1 ? "" : "s"} · a new
            version
          </span>
        </div>
      )}
      <span className="muted" style={{ fontSize: 12 }}>
        confidence {answer.confidence} · rules of thumb for desktop FDM
      </span>
    </div>
  );
}

export function EngineerCard({
  disabled,
  hasRegion,
  onAsk,
  onApplyFix,
  onAdapt,
  onLighten,
}: EngineerCardProps) {
  const [question, setQuestion] = useState("");
  const [purpose, setPurpose] = useState("");
  const [material, setMaterial] = useState("pla");
  const [report, setReport] = useState<EngineeringReportBody | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const job = await onAsk({
        question: question.trim() || null,
        purpose: purpose.trim() || null,
        material_id: material,
      });
      const result = job?.result as { report?: EngineeringReportBody } | null;
      if (result?.report) setReport(result.report);
    } finally {
      setBusy(false);
    }
  }

  const facts = report?.facts;
  return (
    <div className="card stack">
      <div className="row">
        <strong>Ask the engineer</strong>
        <span className="spacer" />
        {hasRegion && <span className="chip">about the outlined area</span>}
      </div>
      <form className="stack" onSubmit={submit}>
        <input
          className="input"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={EXAMPLES[0]}
          disabled={disabled || busy}
        />
        <div className="row">
          <input
            className="input"
            style={{ flex: 1 }}
            value={purpose}
            onChange={(event) => setPurpose(event.target.value)}
            placeholder="What is it for? (держатель для шланга на улице)"
            disabled={disabled || busy}
          />
          <select
            className="input"
            value={material}
            onChange={(event) => setMaterial(event.target.value)}
            disabled={disabled || busy}
          >
            {MATERIALS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>
          <button className="btn primary" type="submit" disabled={disabled || busy}>
            {busy ? "Measuring…" : question.trim() ? "Ask" : "Review the part"}
          </button>
          {onAdapt && (
            <button
              className="btn"
              type="button"
              disabled={disabled || busy}
              title="Walls, floors, holes and corners changed for this material — as a preview"
              onClick={() => void onAdapt(material)}
            >
              Adapt for {MATERIALS.find((m) => m.id === material)?.name ?? material}
            </button>
          )}
          {onLighten && (
            <button
              className="btn"
              type="button"
              disabled={disabled || busy}
              title="Hollow it to a wall this material carries, open at the bottom, bosses kept around the screw holes — a preview"
              onClick={() => void onLighten(material)}
            >
              Make it lighter
            </button>
          )}
        </div>
        <div className="row" style={{ flexWrap: "wrap" }}>
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="chip"
              disabled={disabled || busy}
              onClick={() => setQuestion(example)}
            >
              {example}
            </button>
          ))}
        </div>
      </form>

      {report && (
        <div className="stack">
          {report.answer && (
            <AnswerView answer={report.answer} onApplyFix={onApplyFix} disabled={disabled} />
          )}
          {facts && (
            <div className="muted">
              {facts.walls &&
                `walls from ${facts.walls.min_mm} mm (typical ${facts.walls.median_mm} mm) · `}
              {`recommended ${report.recommended_wall_mm} mm for ${report.material_id.toUpperCase()}`}
              {facts.mass_g[report.material_id] != null &&
                ` · ${facts.mass_g[report.material_id]} g`}
              {facts.region_walls && ` · outlined area ${facts.region_walls.median_mm} mm`}
            </div>
          )}
          {report.materials.length > 0 && (
            <div className="row" style={{ flexWrap: "wrap" }}>
              {report.materials.slice(0, 3).map((choice, index) => (
                <span
                  key={choice.id}
                  className={`chip ${index === 0 ? "selected" : ""}`}
                  title={choice.note}
                >
                  {choice.name}
                  {choice.mass_g != null && ` · ${choice.mass_g} g`}
                </span>
              ))}
            </div>
          )}
          {report.recommendations.length > 0 && (
            <div className="stack">
              <span className="muted">The engineer also noticed:</span>
              {report.recommendations.map((item, index) => (
                <AnswerView
                  key={`${item.intent}-${index}`}
                  answer={item}
                  onApplyFix={onApplyFix}
                  disabled={disabled}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
