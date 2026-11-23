"use client";

import type { HouseBoxBody, InteriorMaterial, PhysicalAiClient } from "@physical-ai/contracts";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

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
  const [upperFloorSetbackMm, setUpperFloorSetbackMm] = useState(0);
  const [addStair, setAddStair] = useState(true);
  const [stairWidthMm, setStairWidthMm] = useState(1_000);
  const [treadDepthMm, setTreadDepthMm] = useState(280);
  const [stepCount, setStepCount] = useState(17);
  const [stairKind, setStairKind] = useState<"straight" | "l_turn" | "u_turn">("straight");
  const [lowerSteps, setLowerSteps] = useState(8);
  const [upperSteps, setUpperSteps] = useState(8);
  const [uFlightSteps, setUFlightSteps] = useState(8);
  const [stairTurn, setStairTurn] = useState<"left" | "right">("left");
  const [stairPlacement, setStairPlacement] = useState<"left" | "center" | "right">("center");
  const [railing, setRailing] = useState(true);
  const [stairMaterialId, setStairMaterialId] = useState<string>("interior.wood.oak-natural.v1");
  const [materials, setMaterials] = useState<InteriorMaterial[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stairEnabled = floors > 1 && shape === "rectangle" && addStair;
  const lTurn = stairKind === "l_turn";
  const uTurn = stairKind === "u_turn";
  const turning = lTurn || uTurn;
  const setbackEnabled = floors > 1 && shape === "rectangle";
  const effectiveUpperInset = setbackEnabled ? upperFloorSetbackMm : 0;
  // A turning landing counts as one riser, mirroring the server's derivation.
  const riserCount = lTurn ? lowerSteps + upperSteps + 1 : uTurn ? 2 * uFlightSteps + 1 : stepCount;
  const riserMm = floorHeightMm / riserCount;
  const stairRunMm = treadDepthMm * (lTurn ? lowerSteps + upperSteps : uTurn ? 2 * uFlightSteps : stepCount);
  const strideMm = 2 * riserMm + treadDepthMm;
  const turningFootprint = lTurn
    ? { x: treadDepthMm * lowerSteps + stairWidthMm, y: stairWidthMm + treadDepthMm * upperSteps }
    : uTurn
      ? { x: treadDepthMm * uFlightSteps + stairWidthMm, y: 2 * stairWidthMm }
    : null;
  const stairFootprint = turningFootprint ?? { x: treadDepthMm * stepCount, y: stairWidthMm };
  const stairFitProblem = stairFootprint.x > lengthMm - 2 * effectiveUpperInset - 700
    || stairFootprint.y > widthMm - 2 * effectiveUpperInset - 700
    ? (ru ? "Лестница с проёмом не помещается в верхний контур с отступом 350 мм от стен." : "The stair and opening do not fit the upper footprint with 350 mm wall clearance.")
    : null;
  const turningProblem = !turning
    ? null
    : riserCount < 10 || riserCount > 30
      ? (ru ? "Нужно 10–30 подъёмов вместе с площадкой." : "Use 10–30 risers including the landing.")
      : strideMm < 550 || strideMm > 700
        ? (ru ? "2 × подъём + проступь должно быть 550–700 мм." : "2 × rise + tread must be 550–700 mm.")
        : null;
  const stairInvalid = stairEnabled && (riserMm < 120 || riserMm > 220 || turningProblem !== null || stairFitProblem !== null);
  const setbackInvalid = setbackEnabled && upperFloorSetbackMm > 0 && (
    lengthMm - 2 * upperFloorSetbackMm < 2_000
    || widthMm - 2 * upperFloorSetbackMm < 2_000
  );

  useEffect(() => {
    void client.listInteriorMaterials()
      .then((items) => setMaterials(items.filter((item) => item.tabs.includes("floor") || item.tabs.includes("furniture"))))
      .catch(() => undefined);
  }, [client]);

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
          upper_floor_setback_mm: setbackEnabled ? upperFloorSetbackMm : 0,
          stair: !stairEnabled
            ? null
            : lTurn
              ? {
                  kind: "l_turn",
                  width_mm: stairWidthMm,
                  tread_depth_mm: treadDepthMm,
                  lower_step_count: lowerSteps,
                  upper_step_count: upperSteps,
                  turn: stairTurn,
                  placement: stairPlacement,
                  railing,
                  material_id: stairMaterialId || null,
                }
              : uTurn
                ? {
                    kind: "u_turn",
                    width_mm: stairWidthMm,
                    tread_depth_mm: treadDepthMm,
                    flight_step_count: uFlightSteps,
                    turn: stairTurn,
                    placement: stairPlacement,
                    railing,
                    material_id: stairMaterialId || null,
                  }
              : {
                  kind: "straight",
                  width_mm: stairWidthMm,
                  tread_depth_mm: treadDepthMm,
                  step_count: stepCount,
                  placement: stairPlacement,
                  railing,
                  material_id: stairMaterialId || null,
                },
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
          <NumberField label={ru ? "Отступ верхних этажей, мм" : "Upper-floor setback, mm"} value={setbackEnabled ? upperFloorSetbackMm : 0} min={0} max={10_000} step={100} onChange={setUpperFloorSetbackMm} disabled={!setbackEnabled} />
        </div>
        <p className="house-total">
          {ru ? "Общая высота" : "Total height"}: <strong>{(floorHeightMm * floors).toLocaleString(language)} {ru ? "мм" : "mm"}</strong>
        </p>
        {floors > 1 && (
          <fieldset className="card stack">
            <legend>{ru ? "Лестница между этажами" : "Stair between floors"}</legend>
            <label className="check">
              <input
                type="checkbox"
                checked={addStair}
                disabled={shape !== "rectangle"}
                onChange={(event) => setAddStair(event.target.checked)}
              />
              {ru ? "Добавить точную лестницу и проёмы перекрытий" : "Add an exact stair and floor openings"}
            </label>
            {shape !== "rectangle" ? (
              <span className="muted">{ru
                ? "Первый bounded-вариант лестницы поддерживает прямоугольный дом."
                : "The first bounded stair flow supports rectangular houses."}</span>
            ) : addStair ? (
              <>
                <div className="house-shapes" role="radiogroup" aria-label={ru ? "Тип лестницы" : "Stair type"}>
                  <div>
                    {([
                      { id: "straight", glyph: "▬", ru: "Прямая", en: "Straight" },
                      { id: "l_turn", glyph: "⌐", ru: "Г-образная с площадкой", en: "L-turn with landing" },
                      { id: "u_turn", glyph: "∩", ru: "П-образная с площадкой", en: "U-turn with landing" },
                    ] as const).map((option) => (
                      <button
                        key={option.id}
                        type="button"
                        role="radio"
                        aria-checked={stairKind === option.id}
                        className={stairKind === option.id ? "house-shape active" : "house-shape"}
                        onClick={() => setStairKind(option.id)}
                      >
                        <span aria-hidden="true">{option.glyph}</span>
                        <strong>{option[language]}</strong>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="house-dimensions">
                  <NumberField label={ru ? "Ширина марша, мм" : "Flight width, mm"} value={stairWidthMm} min={700} max={2_000} step={50} onChange={setStairWidthMm} />
                  <NumberField label={ru ? "Глубина ступени, мм" : "Tread depth, mm"} value={treadDepthMm} min={200} max={400} step={10} onChange={setTreadDepthMm} />
                  {lTurn ? (
                    <>
                      <NumberField label={ru ? "Ступеней в нижнем марше" : "Lower flight steps"} value={lowerSteps} min={3} max={26} step={1} onChange={setLowerSteps} />
                      <NumberField label={ru ? "Ступеней в верхнем марше" : "Upper flight steps"} value={upperSteps} min={3} max={26} step={1} onChange={setUpperSteps} />
                      <label>
                        <span>{ru ? "Поворот" : "Turn"}</span>
                        <select className="input" value={stairTurn} onChange={(event) => setStairTurn(event.target.value as typeof stairTurn)}>
                          <option value="left">{ru ? "Налево" : "Left"}</option>
                          <option value="right">{ru ? "Направо" : "Right"}</option>
                        </select>
                      </label>
                    </>
                  ) : uTurn ? (
                    <>
                      <NumberField label={ru ? "Ступеней в каждом марше" : "Steps per flight"} value={uFlightSteps} min={5} max={14} step={1} onChange={setUFlightSteps} />
                      <label>
                        <span>{ru ? "Сторона разворота" : "Turn side"}</span>
                        <select className="input" value={stairTurn} onChange={(event) => setStairTurn(event.target.value as typeof stairTurn)}>
                          <option value="left">{ru ? "Налево" : "Left"}</option>
                          <option value="right">{ru ? "Направо" : "Right"}</option>
                        </select>
                      </label>
                    </>
                  ) : (
                    <NumberField label={ru ? "Количество ступеней" : "Step count"} value={stepCount} min={10} max={30} step={1} onChange={setStepCount} />
                  )}
                  <label>
                    <span>{ru ? "Расположение" : "Placement"}</span>
                    <select className="input" value={stairPlacement} onChange={(event) => setStairPlacement(event.target.value as typeof stairPlacement)}>
                      <option value="left">{ru ? "Слева" : "Left"}</option>
                      <option value="center">{ru ? "По центру" : "Centre"}</option>
                      <option value="right">{ru ? "Справа" : "Right"}</option>
                    </select>
                  </label>
                  <label>
                    <span>{ru ? "Материал" : "Material"}</span>
                    <select className="input" value={stairMaterialId} onChange={(event) => setStairMaterialId(event.target.value)}>
                      <option value="">{ru ? "Без материала" : "No material"}</option>
                      {materials.map((material) => <option key={material.id} value={material.id}>{ru ? material.name_ru : material.name}</option>)}
                    </select>
                  </label>
                  <label className="check">
                    <input type="checkbox" checked={railing} onChange={(event) => setRailing(event.target.checked)} />
                    {ru ? "Ограждение" : "Railing"}
                  </label>
                </div>
                <p className="house-total">
                  {ru ? "Подъём / проступь / длина" : "Rise / tread / run"}: <strong>{riserMm.toFixed(1)} / {treadDepthMm.toFixed(0)} / {stairRunMm.toFixed(0)} {ru ? "мм" : "mm"}</strong>
                  {turningFootprint && (
                    <>
                      {" · "}{ru ? "площадка" : "landing"} {stairWidthMm.toFixed(0)}×{(stairWidthMm * (uTurn ? 2 : 1)).toFixed(0)}
                      {" · "}{ru ? "габарит" : "footprint"} <strong>{turningFootprint.x.toFixed(0)}×{turningFootprint.y.toFixed(0)} {ru ? "мм" : "mm"}</strong>
                      {" · "}{riserCount} {ru ? "подъёмов" : "risers"}
                    </>
                  )}
                </p>
                {(riserMm < 120 || riserMm > 220) && <div className="error" role="alert">{ru
                  ? "Измените число ступеней: высота ступени должна быть 120–220 мм."
                  : "Change the step count: rise must be 120–220 mm."}</div>}
                {turningProblem && riserMm >= 120 && riserMm <= 220 && <div className="error" role="alert">{turningProblem}</div>}
                {stairFitProblem && !turningProblem && riserMm >= 120 && riserMm <= 220 && <div className="error" role="alert">{stairFitProblem}</div>}
                {turning && <span className="muted">{ru
                  ? `Площадка ${uTurn ? "соединяет два равных параллельных марша" : "квадратная (ширина марша)"} и считается одним подъёмом. Забежные и винтовые лестницы пока не поддерживаются.`
                  : `The landing ${uTurn ? "joins two equal parallel flights" : "is square (one flight width)"} and counts as one riser. Winder and spiral stairs are not supported yet.`}</span>}
              </>
            ) : null}
          </fieldset>
        )}
        {setbackInvalid && <div className="error" role="alert">{ru
          ? "Отступ должен оставлять верхний этаж не меньше 2 000 × 2 000 мм."
          : "The setback must leave an upper floor of at least 2,000 × 2,000 mm."}</div>}
        {error && <div className="error" role="alert">{error}</div>}
        <div className="house-box-actions">
          <button type="button" className="btn" onClick={onBack} disabled={busy}>{ru ? "← Назад" : "← Back"}</button>
          <button type="submit" className="btn primary" disabled={busy || stairInvalid || setbackInvalid}>{busy ? (ru ? "Строим…" : "Building…") : (ru ? "Создать коробку" : "Create box")}</button>
        </div>
      </form>
    </div>
  );
}

function NumberField({ label, value, min, max, step, disabled = false, onChange }: { label: string; value: number; min: number; max: number; step: number; disabled?: boolean; onChange: (value: number) => void }) {
  return (
    <label>
      <span>{label}</span>
      <input className="input" type="number" value={value} min={min} max={max} step={step} disabled={disabled} required onChange={(event) => onChange(event.currentTarget.valueAsNumber)} />
      <small>{min.toLocaleString()}–{max.toLocaleString()}</small>
    </label>
  );
}
