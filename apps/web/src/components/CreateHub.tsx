"use client";

/**
 * The Create menu (F-084): ready scenarios grouped by what the person wants to do. A scan
 * scenario opens a short preparation guide first; everything else goes straight to its tool.
 * The same registry drives the mobile and desktop menus, so every client offers the same paths.
 */
import {
  type CreateScenario,
  SCENARIO_GROUPS,
  getProjectGoal,
  scenariosIn,
} from "@physical-ai/contracts";
import { useEffect, useState } from "react";

type Language = "ru" | "en";

export function CreateHub({
  language,
  initialScenario,
  onChoose,
}: {
  language: Language;
  initialScenario?: string | null;
  /** Called when a scenario is confirmed (after its guide, for scans). */
  onChoose: (scenario: CreateScenario) => void;
}) {
  const [guide, setGuide] = useState<CreateScenario | null>(null);
  const ru = language === "ru";

  const pick = (scenario: CreateScenario) => {
    const scans = scenario.goal ? getProjectGoal(scenario.goal)?.source === "scan" : false;
    if (scans && scenario.guide.length > 0) setGuide(scenario);
    else onChoose(scenario);
  };

  useEffect(() => {
    if (!initialScenario) return;
    for (const group of SCENARIO_GROUPS) {
      const found = scenariosIn(group.id).find((s) => s.id === initialScenario);
      if (found) {
        pick(found);
        return;
      }
    }
    // pick only needs to run for the scenario named in the address
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialScenario]);

  return (
    <>
      {SCENARIO_GROUPS.map((group) => (
        <section key={group.id} className="hub-group" aria-label={group.title[language]}>
          <header>
            <h2>{group.title[language]}</h2>
            <p>{group.note[language]}</p>
          </header>
          <div className="hub-tiles" role="list">
            {scenariosIn(group.id).map((scenario) => (
              <button key={scenario.id} type="button" role="listitem" className="hub-tile" onClick={() => pick(scenario)}>
                <span className="hub-icon" aria-hidden="true">{scenario.icon}</span>
                <strong>{scenario.title[language]}</strong>
                <small>{scenario.note[language]}</small>
                {scenario.prefersLidar && <em className="hub-badge">LiDAR</em>}
              </button>
            ))}
          </div>
        </section>
      ))}
      {guide && (
        <ScenarioGuide
          scenario={guide}
          language={language}
          onClose={() => setGuide(null)}
          onStart={() => {
            const chosen = guide;
            setGuide(null);
            onChoose(chosen);
          }}
        />
      )}
      <p className="hub-hint">
        {ru
          ? "Выбор только подбирает стартовые инструменты: потом доступно всё."
          : "A choice only picks the starting tools; everything stays available later."}
      </p>
    </>
  );
}

function ScenarioGuide({
  scenario,
  language,
  onClose,
  onStart,
}: {
  scenario: CreateScenario;
  language: Language;
  onClose: () => void;
  onStart: () => void;
}) {
  const [step, setStep] = useState(0);
  const ru = language === "ru";
  const last = step === scenario.guide.length - 1;
  const current = scenario.guide[step];

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!current) return null;
  return (
    <div className="guide-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="guide-sheet" role="dialog" aria-modal="true" aria-label={scenario.title[language]}>
        <button type="button" className="guide-close" onClick={onClose} aria-label={ru ? "Закрыть" : "Close"}>×</button>
        <h2>{ru ? "Создание: " : "Creating: "}{scenario.title[language]}</h2>
        <ol className="guide-steps">
          {scenario.guide.map((item, index) => (
            <li key={index} className={index < step ? "done" : index === step ? "current" : ""}>
              <button type="button" onClick={() => setStep(index)}>
                <span className="guide-dot" aria-hidden="true">{index < step ? "✓" : ""}</span>
                {item.title[language]}
              </button>
            </li>
          ))}
        </ol>
        <h3>{current.title[language]}</h3>
        <ul className="guide-tips">
          {current.tips.map((tip, index) => (
            <li key={index}>{tip[language]}</li>
          ))}
        </ul>
        {scenario.limits && step === 1 && (
          <p className="guide-limits">
            {ru
              ? `Нужно от ${scenario.limits.minFrames} до ${scenario.limits.maxFrames} кадров.`
              : `You will need ${scenario.limits.minFrames} to ${scenario.limits.maxFrames} frames.`}
          </p>
        )}
        {scenario.prefersLidar && (
          <p className="guide-limits">
            {ru
              ? "Точные размеры даёт LiDAR (iPhone/iPad Pro). Без него размер придётся указать вручную."
              : "LiDAR (iPhone/iPad Pro) gives measured sizes. Without it you set one size by hand."}
          </p>
        )}
        <div className="guide-actions">
          {step > 0 && <button type="button" className="btn" onClick={() => setStep(step - 1)}>{ru ? "Назад" : "Back"}</button>}
          {!last && <button type="button" className="btn" onClick={() => setStep(step + 1)}>{ru ? "Далее" : "Next"}</button>}
          <button type="button" className="btn primary" onClick={onStart}>{ru ? "Начать съёмку" : "Start capture"}</button>
        </div>
        <div className="guide-pages" aria-hidden="true">
          {scenario.guide.map((_, index) => <i key={index} className={index === step ? "on" : ""} />)}
        </div>
      </div>
    </div>
  );
}
