"use client";

/** First-run story shared with mobile: idea → precise edit → production. */
import { useEffect, useState } from "react";

import { SovaMark } from "@/components/SovaMark";

const KEY = "sova.onboarded.v2";

type SlideKind = "idea" | "edit" | "export";

interface Slide {
  kind: SlideKind;
  number: string;
  title: string;
  note: string;
  actions: readonly string[];
}

const SLIDES: Record<"ru" | "en", readonly Slide[]> = {
  ru: [
    {
      kind: "idea",
      number: "01",
      title: "От идеи к модели",
      note: "Опишите предмет, добавьте фото или снимите его камерой — Sova соберёт редактируемую 3D-модель.",
      actions: ["По описанию", "С камерой"],
    },
    {
      kind: "edit",
      number: "02",
      title: "Меняйте точно",
      note: "Выбирайте детали прямо на модели, задавайте размеры в миллиметрах и сохраняйте каждое изменение.",
      actions: ["Выделение области", "Точные размеры", "Слои и история"],
    },
    {
      kind: "export",
      number: "03",
      title: "Подготовьте к печати",
      note: "Проверьте геометрию и экспортируйте модель в нужном формате без потери масштаба.",
      actions: ["Проверка модели"],
    },
  ],
  en: [
    {
      kind: "idea",
      number: "01",
      title: "From idea to model",
      note: "Describe an object, add photos or capture it — Sova builds an editable 3D model.",
      actions: ["From a description", "With the camera"],
    },
    {
      kind: "edit",
      number: "02",
      title: "Edit with precision",
      note: "Select details on the model, enter millimetres and keep every change in history.",
      actions: ["Area selection", "Exact dimensions", "Layers and history"],
    },
    {
      kind: "export",
      number: "03",
      title: "Prepare for production",
      note: "Check the geometry and export in the format you need without losing scale.",
      actions: ["Model check"],
    },
  ],
};

const ACTION_ICONS: Record<SlideKind, readonly string[]> = {
  idea: ["▤", "◉"],
  edit: ["↖", "↔", "▱"],
  export: ["✓"],
};

export function Onboarding({ language }: { language: "ru" | "en" }) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    try {
      if (!window.localStorage.getItem(KEY)) setOpen(true);
    } catch {
      // Storage blocked: avoid a welcome that appears on every visit.
    }
  }, []);

  const finish = () => {
    try {
      window.localStorage.setItem(KEY, "1");
    } catch {
      // The welcome may appear again if storage is unavailable.
    }
    setOpen(false);
  };

  if (!open) return null;
  const slides = SLIDES[language];
  const slide = slides[step] as Slide;
  const last = step === slides.length - 1;
  const ru = language === "ru";

  return (
    <div className="onboarding" role="dialog" aria-modal="true" aria-label={ru ? "Добро пожаловать" : "Welcome"}>
      <header className="onboarding-topbar">
        <span className="onboarding-brand"><SovaMark /> Sova <b>3D</b></span>
        <button type="button" className="onboarding-skip" onClick={finish}>{ru ? "Пропустить" : "Skip"}</button>
      </header>

      <div className="onboarding-stage">
        <HeroVisual kind={slide.kind} language={language} />
        <section className="onboarding-story">
          <div className="onboarding-step"><strong>{slide.number}</strong><i /><span>03</span></div>
          <h2>{slide.title}</h2>
          <p>{slide.note}</p>
          <div className="onboarding-actions">
            {slide.actions.map((action, index) => (
              <div className="onboarding-action" key={action}>
                <i aria-hidden="true">{ACTION_ICONS[slide.kind][index]}</i>
                <span>{action}</span>
                <b aria-hidden="true">›</b>
              </div>
            ))}
          </div>
          {slide.kind === "export" && (
            <div className="onboarding-formats" aria-label={ru ? "Форматы экспорта" : "Export formats"}>
              {(["STL", "3MF", "GLB"] as const).map((format, index) => <span className={index === 0 ? "active" : ""} key={format}>{format}</span>)}
            </div>
          )}
        </section>
      </div>

      <footer className="onboarding-footer">
        <div className="onboarding-dots">
          {slides.map((_, index) => (
            <button key={index} type="button" className={index === step ? "on" : ""} aria-label={`${index + 1} / ${slides.length}`} onClick={() => setStep(index)} />
          ))}
        </div>
        <button type="button" className="btn primary onboarding-next" onClick={() => (last ? finish() : setStep((current) => current + 1))}>
          {last ? (ru ? "Начать работу" : "Get started") : ru ? "Далее" : "Next"}
        </button>
      </footer>
    </div>
  );
}

function HeroVisual({ kind, language }: { kind: SlideKind; language: "ru" | "en" }) {
  const ru = language === "ru";
  return (
    <div className="onboarding-visual" aria-hidden="true">
      <div className="onboarding-grid" />
      <div className="onboarding-glow" />
      <svg className="onboarding-object" viewBox="0 0 520 390" fill="none">
        <path d="M138 112 265 45l126 67-126 68-127-68Z" fill="#ff7a2b" />
        <path d="m138 112 127 68v143l-127-72V112Z" fill="#b63b08" />
        <path d="m391 112-126 68v143l126-72V112Z" fill="#df500d" />
        <path d="m178 132 87 46 87-46v72l-87 48-87-48v-72Z" fill="#151617" stroke="#ff9a5c" strokeWidth="4" />
        <path d="m138 112 127 68 126-68M265 180v143" stroke="#ffbb91" strokeOpacity=".72" strokeWidth="3" />
      </svg>
      {kind === "idea" && <div className="onboarding-float-chip"><SovaMark /><span><b>{ru ? "Новая модель" : "New model"}</b><small>{ru ? "редактируемая геометрия" : "editable geometry"}</small></span></div>}
      {kind === "edit" && <div className="onboarding-measure"><span /><b>{ru ? "124 мм" : "124 mm"}</b><span /></div>}
      {kind === "export" && <div className="onboarding-ready"><b>✓</b><span><strong>{ru ? "Геометрия проверена" : "Geometry checked"}</strong><small>{ru ? "Масштаб 1:1 · без ошибок" : "Scale 1:1 · no errors"}</small></span></div>}
    </div>
  );
}
