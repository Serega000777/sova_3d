"use client";

/**
 * AI Assembly + Fit Test (T-180, F-010/F-027).
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
  const [autoPlace, setAutoPlace] = useState(true);
  const [rotation, setRotation] = useState(0);
  const [report, setReport] = useState<FitTestReport | null>(null);
  const [busy, setBusy] = useState(false);

  const chosen = others.find((p) => p.id === (otherId || others[0]?.id));

  async function run() {
    if (!chosen?.head_version_id) return;
    setBusy(true);
    try {
      const job = await onRun({
        version_b_id: chosen.head_version_id,
        placement: { align, offset_mm: [offset.x, offset.y, offset.z], rotate_z_deg: rotation },
        auto_place: autoPlace,
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
  const ru = typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru");
  const verdicts: Record<string, string> = {
    collides: "пересечение",
    press: "плотная",
    transition: "переходная",
    sliding: "скользящая",
    loose: "свободная",
    apart: "не соприкасаются",
  };
  const poseNames: Record<string, string> = {
    centre: "По центру",
    top: "Сверху",
    right: "Справа",
    front: "Спереди",
    bottom: "Снизу",
    left: "Слева",
    back: "Сзади",
  };
  const poseLabel = (label: string) => {
    if (!ru) return label;
    const [name, angle] = label.split(" · ");
    return `${poseNames[name] ?? name} · ${angle}`;
  };
  return (
    <div className="card stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{ru ? "AI-сборка и посадка" : "AI assembly & fit"}</strong>
        <span className="chip">F-010</span>
      </div>
      {others.length === 0 ? (
        <span className="muted">
          {ru
            ? "Создайте или импортируйте вторую деталь отдельным проектом — здесь система соберёт их вместе."
            : "Make or import the other part as its own project, then assemble it here."}
        </span>
      ) : (
        <>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <button
              type="button"
              className={`btn ${autoPlace ? "primary" : ""}`}
              onClick={() => setAutoPlace(true)}
              disabled={disabled || busy}
            >
              {ru ? "Автопозиция" : "Auto position"}
            </button>
            <button
              type="button"
              className={`btn ${!autoPlace ? "primary" : ""}`}
              onClick={() => setAutoPlace(false)}
              disabled={disabled || busy}
            >
              {ru ? "Вручную" : "Manual"}
            </button>
            {autoPlace && (
              <span className="muted">
                {ru
                  ? "ИИ проверит центр, четыре поворота и касание каждой гранью."
                  : "AI checks the centre, four rotations and every touching face."}
              </span>
            )}
          </div>
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
            {!autoPlace && (
              <select
                className="input"
                value={align}
                onChange={(event) => setAlign(event.target.value as "centre" | "origin")}
                disabled={disabled || busy}
              >
                <option value="centre">{ru ? "по центру детали" : "centred on this part"}</option>
                <option value="origin">{ru ? "по исходной точке" : "at its own origin"}</option>
              </select>
            )}
            {!autoPlace && (["x", "y", "z"] as const).map((axis) => (
              <label key={axis} className="muted" style={{ fontSize: 12 }}>
                {ru ? `Смещение ${axis}, мм` : `${axis} offset (mm)`}
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
            {!autoPlace && (
              <label className="muted" style={{ fontSize: 12 }}>
                {ru ? "Поворот Z, °" : "Z rotation, °"}
                <input
                  className="input"
                  type="number"
                  step="15"
                  style={{ width: 84, display: "block" }}
                  value={rotation}
                  disabled={disabled || busy}
                  onChange={(event) => setRotation(Number(event.target.value))}
                />
              </label>
            )}
            <select
              className="input"
              value={wanted}
              onChange={(event) => setWanted(event.target.value as FitTestBody["wanted"])}
              disabled={disabled || busy}
            >
              {FITS.map((fit) => (
                <option key={fit} value={fit}>
                  {ru ? `Нужна: ${verdicts[fit] ?? fit}` : `want a ${fit} fit`}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn primary"
              disabled={disabled || busy || !chosen}
              onClick={() => void run()}
            >
              {busy
                ? ru
                  ? "Собираю…"
                  : "Assembling…"
                : autoPlace
                  ? ru
                    ? "Собрать автоматически"
                    : "Assemble automatically"
                  : ru
                    ? "Проверить положение"
                    : "Check placement"}
            </button>
          </div>
          {measured && advice && (
            <div className="stack" style={{ gap: 6 }}>
              <div>
                <span className={`chip ${verdictClass(measured.verdict)}`}>
                  {ru ? verdicts[measured.verdict] ?? measured.verdict : measured.verdict}
                </span>{" "}
                {advice.summary}
              </div>
              {measured.placement && (
                <span className="muted">
                  {ru ? "Положение B" : "Part B position"}: {measured.placement.offset_mm.map((v) => Number(v).toFixed(1)).join(" · ")} mm · Z {measured.placement.rotate_z_deg}°
                </span>
              )}
              <span className="muted">
                {measured.max_penetration_mm > 0 &&
                  (ru
                    ? `пересечение ${measured.max_penetration_mm} мм на сторону`
                    : `overlap ${measured.max_penetration_mm} mm per side`)}
                {measured.min_clearance_mm != null &&
                  (ru
                    ? `зазор ${measured.min_clearance_mm} мм на сторону`
                    : `gap ${measured.min_clearance_mm} mm per side`)}
                {measured.interference_mm3 != null &&
                  ` · ${measured.interference_mm3} mm³ of interference`}
              </span>
              {advice.recommendation && <div>{advice.recommendation}</div>}
              {!!measured.candidates?.length && (
                <div className="row" style={{ flexWrap: "wrap" }}>
                  {measured.candidates.map((candidate, index) => (
                    <button
                      type="button"
                      className={`btn ${index === 0 ? "primary" : ""}`}
                      key={`${candidate.label}-${index}`}
                      disabled={disabled || busy}
                      title={`${candidate.verdict} · ${candidate.placement.offset_mm.join(", ")} mm`}
                      onClick={() => {
                        setAutoPlace(false);
                        setAlign(candidate.placement.align);
                        setOffset({
                          x: candidate.placement.offset_mm[0] ?? 0,
                          y: candidate.placement.offset_mm[1] ?? 0,
                          z: candidate.placement.offset_mm[2] ?? 0,
                        });
                        setRotation(candidate.placement.rotate_z_deg);
                      }}
                    >
                      {poseLabel(candidate.label)}
                    </button>
                  ))}
                </div>
              )}
              {advice.fix && (
                <div className="row">
                  <button
                    type="button"
                    className="btn primary"
                    disabled={disabled}
                    onClick={() => void onApplyFix(advice.fix!)}
                  >
                    {ru ? "Применить" : "Apply"}: {advice.fix.label}
                  </button>
                  <span className="muted">{ru ? "создаст новую версию детали" : "a new version of this part"}</span>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
