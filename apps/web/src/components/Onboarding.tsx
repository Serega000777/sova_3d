"use client";

/** First-run welcome: three short screens that say what the product really does. */
import { useEffect, useState } from "react";

const KEY = "sova.onboarded.v1";

const SLIDES = {
  ru: [
    { icon: "✦", title: "Создавайте 3D из описания, фото и сканов", note: "Опишите предмет словами, загрузите снимок или отсканируйте — получите модель, которую можно редактировать." },
    { icon: "⌂", title: "Сканируйте комнаты и здания", note: "Комната за комнатой собирается в план дома; фасады снимаются отдельными проходами. План можно разметить пинами и облаками." },
    { icon: "⬡", title: "Редактируйте точно", note: "Сетка и привязка, выбор вершин, рёбер и граней, круглые и квадратные детали, накатка. Экспорт для печати, игр и CAD." },
  ],
  en: [
    { icon: "✦", title: "Create 3D from words, photos and scans", note: "Describe an object, upload a photo or scan it — you get a model you can edit." },
    { icon: "⌂", title: "Scan rooms and buildings", note: "Room by room becomes a house plan; facades are captured in separate passes. Mark the plan up with pins and clouds." },
    { icon: "⬡", title: "Edit with precision", note: "Grid and snapping, vertex, edge and face selection, round and square details, knurling. Export for printing, games and CAD." },
  ],
} as const;

export function Onboarding({ language }: { language: "ru" | "en" }) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    try {
      if (!window.localStorage.getItem(KEY)) setOpen(true);
    } catch {
      // storage blocked: show nothing rather than nag on every visit
    }
  }, []);

  const finish = () => {
    try {
      window.localStorage.setItem(KEY, "1");
    } catch {
      // the welcome simply shows again next time
    }
    setOpen(false);
  };

  if (!open) return null;
  const slides = SLIDES[language];
  const slide = slides[step] as (typeof slides)[number];
  const last = step === slides.length - 1;
  const ru = language === "ru";
  return (
    <div className="onboarding" role="dialog" aria-modal="true" aria-label={ru ? "Добро пожаловать" : "Welcome"}>
      <button type="button" className="onboarding-skip" onClick={finish}>{ru ? "Пропустить" : "Skip"}</button>
      <div className="onboarding-icon" aria-hidden="true">{slide.icon}</div>
      <h2>{slide.title}</h2>
      <p>{slide.note}</p>
      <div className="onboarding-dots" aria-hidden="true">
        {slides.map((_, index) => <i key={index} className={index === step ? "on" : ""} />)}
      </div>
      <button type="button" className="btn primary onboarding-next" onClick={() => (last ? finish() : setStep(step + 1))}>
        {last ? (ru ? "Начать" : "Get started") : ru ? "Далее" : "Next"}
      </button>
    </div>
  );
}
