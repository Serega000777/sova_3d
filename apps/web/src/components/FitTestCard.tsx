"use client";

/**
 * AI Fit Test (T-131, F-027): put another part against this one and hear whether it fits.
 *
 * Pick a project in the workspace (its current model is part B), say how it sits — centred
 * on this part by default, then offset — and what fit you want. The verdict comes back with
 * the gap or the overlap in millimetres, the engineer's sentence, and a one-tap fix when
 * this part's plan has the opening the other part goes into.
 */
import type { FitTestBody, FitTestReport, Job, Project } from "@physical-ai/contracts";
import { useState } from "react";

const FITS: FitTestBody["wanted"][] = ["clearance", "sliding", "transition", "press"];

export interface FitTestCardProps {
  projects: Project[];
  currentProjectId: string;
  disabled: boolean;
  onRun: (body: Omit<FitTestBody, "version_a_id">) => Promise<Job | null>;
  onApplyFix: (fix: NonNullable<FitTestReport["advice"]["fix"]>) => Promise<void>;
}

function verdictClass(verdict: string): string {
  if (verdict === "collides") return "status-red";
  if (verdict === "apart" || verdict === "loose") return "status-yellow";
  return "status-green";
}

export function FitTestCard({
  projects,
  currentProjectId,
  disabled,
  onRun,
  onApplyFix,
}: FitTestCardProps) {
  const others = projects.filter((p) => p.id !== currentProjectId && p.head_version_id);
  const [otherId, setOtherId] = useState<string>("");
  const [offset, setOffset] = useState({ x: 0, y: 0, z: 0 });
  const [align, setAlign] = useState<"centre" | "origin">("centre");
  const [wanted, setWanted] = useState<FitTestBody["wanted"]>("sliding");
  const [report, setReport] = useState<FitTestReport | null>(null);
  const [busy, setBusy] = useState(false);

  const chosen = others.find((p) => p.id === (otherId || others[0]?.id));

  async function run() {
    if (!chosen?.head_version_id) return;
    setBusy(true);
    try {
      const job = await onRun({
        version_b_id: chosen.head_version_id,
        placement: { align, offset_mm: [offset.x, offset.y, offset.z], rotate_z_deg: 0 },
        wanted,
        language:
          typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru")
            ? "ru"
            : "en",
      });
      const result = job?.result as { report?: FitTestReport } | null;
      if (result?.report) setReport(result.report);
    } finally {
      setBusy(false);
    }
  }

  const measured = report?.measured;
  const advice = report?.advice;
  return (
    <div className="card stack">
      <strong>Fit test</strong>
      {others.length === 0 ? (
        <span className="muted">
          Make or import the other part as its own project, then put it against this one here.
        </span>
      ) : (
        <>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <select
              className="input"
              value={chosen?.id ?? ""}
              onChange={(event) => setOtherId(event.target.value)}
              disabled={disabled || busy}
            >
              {others.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <select
              className="input"
              value={align}
              onChange={(event) => setAlign(event.target.value as "centre" | "origin")}
              disabled={disabled || busy}
            >
              <option value="centre">centred on this part</option>
              <option value="origin">at its own origin</option>
            </select>
            {(["x", "y", "z"] as const).map((axis) => (
              <label key={axis} className="muted" style={{ fontSize: 12 }}>
                {axis} offset (mm)
                <input
                  className="input"
                  type="number"
                  step="0.5"
                  style={{ width: 84, display: "block" }}
                  value={offset[axis]}
                  disabled={disabled || busy}
                  onChange={(event) =>
                    setOffset((all) => ({ ...all, [axis]: Number(event.target.value) }))
                  }
                />
              </label>
            ))}
            <select
              className="input"
              value={wanted}
              onChange={(event) => setWanted(event.target.value as FitTestBody["wanted"])}
              disabled={disabled || busy}
            >
              {FITS.map((fit) => (
                <option key={fit} value={fit}>
                  want a {fit} fit
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn primary"
              disabled={disabled || busy || !chosen}
              onClick={() => void run()}
            >
              {busy ? "Fitting…" : "Put them together"}
            </button>
          </div>
          {measured && advice && (
            <div className="stack" style={{ gap: 6 }}>
              <div>
                <span className={`chip ${verdictClass(measured.verdict)}`}>{measured.verdict}</span>{" "}
                {advice.summary}
              </div>
              <span className="muted">
                {measured.max_penetration_mm > 0 &&
                  `overlap ${measured.max_penetration_mm} mm per side`}
                {measured.min_clearance_mm != null &&
                  `gap ${measured.min_clearance_mm} mm per side`}
                {measured.interference_mm3 != null &&
                  ` · ${measured.interference_mm3} mm³ of interference`}
              </span>
              {advice.recommendation && <div>{advice.recommendation}</div>}
              {advice.fix && (
                <div className="row">
                  <button
                    type="button"
                    className="btn primary"
                    disabled={disabled}
                    onClick={() => void onApplyFix(advice.fix!)}
                  >
                    Apply: {advice.fix.label}
                  </button>
                  <span className="muted">a new version of this part</span>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
