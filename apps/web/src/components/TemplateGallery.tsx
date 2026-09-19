"use client";

/**
 * Quick starts (T-125, F-070): a first project that is not a blank page.
 *
 * Each card is a sentence the planner is known to build, with the few numbers worth
 * changing before it is built. Picking one creates the project and starts the build; the
 * project page then shows what to try next.
 */
import type { Template } from "@physical-ai/contracts";
import { useState } from "react";

export interface TemplateGalleryProps {
  templates: Template[];
  language: "en" | "ru";
  disabled: boolean;
  onStart: (template: Template, params: Record<string, number>) => Promise<void>;
}

function TemplateCard({
  template,
  language,
  disabled,
  onStart,
}: {
  template: Template;
  language: "en" | "ru";
  disabled: boolean;
  onStart: TemplateGalleryProps["onStart"];
}) {
  const [params, setParams] = useState<Record<string, number>>(() =>
    Object.fromEntries(template.parameters.map((p) => [p.id, p.default])),
  );
  const [starting, setStarting] = useState(false);
  const title = language === "ru" ? template.title_ru : template.title_en;
  const description = language === "ru" ? template.description_ru : template.description_en;

  async function start() {
    setStarting(true);
    try {
      await onStart(template, params);
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="card stack">
      <strong>{title}</strong>
      <span className="muted">{description}</span>
      {template.parameters.length > 0 && (
        <div className="row" style={{ flexWrap: "wrap" }}>
          {template.parameters.map((parameter) => (
            <label key={parameter.id} className="muted" style={{ fontSize: 12 }}>
              {language === "ru" ? parameter.label_ru : parameter.label_en}
              {parameter.unit && ` (${parameter.unit})`}
              <input
                className="input"
                type="number"
                style={{ width: 88, display: "block" }}
                min={parameter.min}
                max={parameter.max}
                value={params[parameter.id]}
                disabled={disabled || starting}
                onChange={(event) =>
                  setParams((all) => ({ ...all, [parameter.id]: Number(event.target.value) }))
                }
              />
            </label>
          ))}
        </div>
      )}
      <div className="row">
        <button
          type="button"
          className="btn primary"
          disabled={disabled || starting}
          onClick={() => void start()}
        >
          {starting ? (language === "ru" ? "Строим…" : "Building…") : language === "ru" ? "Начать" : "Start"}
        </button>
      </div>
    </div>
  );
}

export function TemplateGallery({ templates, language, disabled, onStart }: TemplateGalleryProps) {
  if (!templates.length) return null;
  return (
    <div className="stack">
      <div className="row">
        <strong>{language === "ru" ? "Начните с шаблона" : "Start from a template"}</strong>
        <span className="muted">
          {language === "ru"
            ? "готовые детали, которые точно построятся — и что попробовать дальше"
            : "parts that are known to build — and what to try on them next"}
        </span>
      </div>
      <div className="grid projects">
        {templates.map((template) => (
          <TemplateCard
            key={template.id}
            template={template}
            language={language}
            disabled={disabled}
            onStart={onStart}
          />
        ))}
      </div>
    </div>
  );
}
