"use client";

import type { HouseBoxBody, PhysicalAiClient } from "@physical-ai/contracts";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

type Shape = HouseBoxBody["shape"];
type Language = "ru" | "en";

const SHAPES: readonly { id: Shape; glyph: string; ru: string; en: string }[] = [
  { id: "rectangle", glyph: "▭", ru: "Прямоугольник", en: "Rectangle" },
  { id: "l_shape", glyph: "⌞", ru: "Г-образная", en: "L shape" },
  { id: "t_shape", glyph: "⊤", ru: "Т-образная", en: "T shape" },
];

export function HouseBoxWizard({
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
  const [lengthMm, setLengthMm] = useState(12_000);
  const [widthMm, setWidthMm] = useState(8_000);
  const [floorHeightMm, setFloorHeightMm] = useState(3_000);
  const [floors, setFloors] = useState(1);
  const [shape, setShape] = useState<Shape>("rectangle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const accepted = await client.buildHouseBox(
        {
          workspace_id: workspaceId,
          label: ru ? "Новый дом" : "New house",
          length_mm: lengthMm,
          width_mm: widthMm,
          floor_height_mm: floorHeightMm,
          floors,
          shape,
        },
        crypto.randomUUID(),
      );
      await client.waitForJob(accepted.job.job_id, { intervalMs: 1_000 });
      router.push(`/projects/${accepted.project_id}?goal=house_design`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBusy(false);
    }
  }

  return (
    <div className="create-studio house-box-wizard">
      <div className="create-intro">
        <span className="eyebrow">{ru ? "БЫСТРЫЙ СТАРТ" : "QUICK START"}</span>
        <h1>{ru ? "Создать дизайн дома" : "Create a house design"}</h1>
        <p>{ru ? "Выберите форму и размеры — мы создадим редактируемую CAD-коробку дома." : "Choose a shape and dimensions to create an editable CAD house mass."}</p>
      </div>
      <form className="house-box-form card" onSubmit={create}>
        <fieldset className="house-shapes">
          <legend>{ru ? "Форма дома" : "House shape"}</legend>
          <div>
            {SHAPES.map((option) => (
              <button
                key={option.id}
                type="button"
                className={shape === option.id ? "house-shape active" : "house-shape"}
                aria-pressed={shape === option.id}
                onClick={() => setShape(option.id)}
              >
                <span aria-hidden="true">{option.glyph}</span>
                <strong>{option[language]}</strong>
              </button>
            ))}
          </div>
        </fieldset>
        <div className="house-dimensions">
          <NumberField label={ru ? "Длина, мм" : "Length, mm"} value={lengthMm} min={2_000} max={50_000} step={100} onChange={setLengthMm} />
          <NumberField label={ru ? "Ширина, мм" : "Width, mm"} value={widthMm} min={2_000} max={50_000} step={100} onChange={setWidthMm} />
          <NumberField label={ru ? "Высота этажа, мм" : "Floor height, mm"} value={floorHeightMm} min={2_200} max={6_000} step={100} onChange={setFloorHeightMm} />
          <NumberField label={ru ? "Этажей" : "Floors"} value={floors} min={1} max={3} step={1} onChange={setFloors} />
        </div>
        <p className="house-total">
          {ru ? "Общая высота" : "Total height"}: <strong>{(floorHeightMm * floors).toLocaleString(language)} {ru ? "мм" : "mm"}</strong>
        </p>
        {error && <div className="error" role="alert">{error}</div>}
        <div className="house-box-actions">
          <button type="button" className="btn" onClick={onBack} disabled={busy}>{ru ? "← Назад" : "← Back"}</button>
          <button type="submit" className="btn primary" disabled={busy}>{busy ? (ru ? "Строим…" : "Building…") : (ru ? "Создать коробку" : "Create box")}</button>
        </div>
      </form>
    </div>
  );
}

function NumberField({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }) {
  return (
    <label>
      <span>{label}</span>
      <input className="input" type="number" value={value} min={min} max={max} step={step} required onChange={(event) => onChange(event.currentTarget.valueAsNumber)} />
      <small>{min.toLocaleString()}–{max.toLocaleString()}</small>
    </label>
  );
}
