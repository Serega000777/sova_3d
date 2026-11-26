"use client";

import { checkSpiralStair, checkUpperFloorSetbackLevels, checkUpperFloorSetbackSides, checkWinderStair, type HouseBoxBody, type InteriorMaterial, type PhysicalAiClient, SPIRAL_STAIR_PROBLEM_TEXT, stackedUpperFloorInsets, stairFootprintFits, upperFloorInsets, upperFloorSetbackProblemText, type UpperFloorSetbackSides, WINDER_STAIR_PROBLEM_TEXT } from "@physical-ai/contracts";
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
  const [perSideSetback, setPerSideSetback] = useState(false);
  const [setbackSides, setSetbackSides] = useState<UpperFloorSetbackSides>({ xMinMm: 0, xMaxMm: 0, yMinMm: 0, yMaxMm: 0 });
  const [topFloorSides, setTopFloorSides] = useState<UpperFloorSetbackSides>({ xMinMm: 0, xMaxMm: 0, yMinMm: 0, yMaxMm: 0 });
  const [addStair, setAddStair] = useState(true);
  const [stairWidthMm, setStairWidthMm] = useState(1_000);
  const [treadDepthMm, setTreadDepthMm] = useState(280);
  const [stepCount, setStepCount] = useState(17);
  const [stairKind, setStairKind] = useState<"straight" | "l_turn" | "u_turn" | "winder_turn" | "spiral">("straight");
  const [lowerSteps, setLowerSteps] = useState(8);
  const [upperSteps, setUpperSteps] = useState(8);
  const [uFlightSteps, setUFlightSteps] = useState(8);
  const [winderLowerSteps, setWinderLowerSteps] = useState(7);
  const [winderUpperSteps, setWinderUpperSteps] = useState(7);
  const [newelMm, setNewelMm] = useState(250);
  const [spiralDiameterMm, setSpiralDiameterMm] = useState(2_200);
  const [spiralPostDiameterMm, setSpiralPostDiameterMm] = useState(200);
  const [spiralSteps, setSpiralSteps] = useState(15);
  const [spiralSweepDeg, setSpiralSweepDeg] = useState(300);
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
  const winderTurn = stairKind === "winder_turn";
  const spiralStair = stairKind === "spiral";
  const turning = lTurn || uTurn || winderTurn;
  const setbackEnabled = floors > 1 && shape === "rectangle";
  const effectiveUpperInset = setbackEnabled && !perSideSetback ? upperFloorSetbackMm : 0;
  // Two floors keep the single per-side field; three floors send one entry per upper floor.
  const effectiveSides = setbackEnabled && perSideSetback && floors === 2 ? setbackSides : null;
  const perFloorSides = setbackEnabled && perSideSetback && floors === 3 ? [setbackSides, topFloorSides] : null;
  // One stair rises through every upper floor, so it is checked against the tightest wall of each.
  const stairSides = perFloorSides ? stackedUpperFloorInsets(perFloorSides) : effectiveSides;
  const insets = upperFloorInsets(effectiveUpperInset, stairSides);
  const winder = checkWinderStair({
    widthMm: stairWidthMm,
    treadMm: treadDepthMm,
    lowerSteps: winderLowerSteps,
    upperSteps: winderUpperSteps,
    newelMm,
    placement: stairPlacement,
    houseLengthMm: lengthMm,
    houseWidthMm: widthMm,
    floorHeightMm,
    upperFloorSetbackMm: effectiveUpperInset,
    upperFloorSetbackSides: stairSides,
  });
  const spiral = checkSpiralStair({
    diameterMm: spiralDiameterMm,
    postDiameterMm: spiralPostDiameterMm,
    stepCount: spiralSteps,
    sweepDeg: spiralSweepDeg,
    placement: stairPlacement,
    houseLengthMm: lengthMm,
    houseWidthMm: widthMm,
    floorHeightMm,
    upperFloorSetbackMm: effectiveUpperInset,
    upperFloorSetbackSides: stairSides,
  });
  // A turning landing counts as one riser and so does every winder, like the server's derivation.
  const riserCount = spiralStair ? spiralSteps : winderTurn ? winder.riserCount : lTurn ? lowerSteps + upperSteps + 1 : uTurn ? 2 * uFlightSteps + 1 : stepCount;
  const riserMm = spiralStair ? spiral.riseMm : floorHeightMm / riserCount;
  const stairRunMm = spiralStair ? spiral.goingMm * spiralSteps : treadDepthMm * (winderTurn ? winderLowerSteps + winderUpperSteps : lTurn ? lowerSteps + upperSteps : uTurn ? 2 * uFlightSteps : stepCount);
  const strideMm = 2 * riserMm + treadDepthMm;
  const turningFootprint = winderTurn
    ? winder.footprint
    : lTurn
    ? { x: treadDepthMm * lowerSteps + stairWidthMm, y: stairWidthMm + treadDepthMm * upperSteps }
    : uTurn
      ? { x: treadDepthMm * uFlightSteps + stairWidthMm, y: 2 * stairWidthMm }
    : null;
  const stairFootprint = spiralStair ? spiral.footprint : turningFootprint ?? { x: treadDepthMm * stepCount, y: stairWidthMm };
  // Winder and spiral checks already include fit; the rest use the same server placement rule.
  const stairFitProblem = spiralStair || winderTurn
    ? null
    : !stairFootprintFits({ footprint: stairFootprint, placement: stairPlacement, houseLengthMm: lengthMm, houseWidthMm: widthMm, insets })
    ? (ru ? "Лестница с проёмом не помещается в верхний контур с отступом 350 мм от стен." : "The stair and opening do not fit the upper footprint with 350 mm wall clearance.")
    : null;
  const turningProblem = spiralStair
    ? spiral.problem && SPIRAL_STAIR_PROBLEM_TEXT[spiral.problem][language]
    : !turning
    ? null
    : winderTurn
    ? winder.problem && WINDER_STAIR_PROBLEM_TEXT[winder.problem][language]
    : riserCount < 10 || riserCount > 30
      ? (ru ? "Нужно 10–30 подъёмов вместе с площадкой." : "Use 10–30 risers including the landing.")
      : strideMm < 550 || strideMm > 700
        ? (ru ? "2 × подъём + проступь должно быть 550–700 мм." : "2 × rise + tread must be 550–700 mm.")
        : null;
  // The shared winder check already covers rise, fit and every bound with one message.
  const riseInvalid = !winderTurn && !spiralStair && (riserMm < 120 || riserMm > 220);
  const stairInvalid = stairEnabled && (riserMm < 120 || riserMm > 220 || turningProblem !== null || stairFitProblem !== null);
  const sidesProblem = perFloorSides
    ? checkUpperFloorSetbackLevels(perFloorSides, floors, lengthMm, widthMm)
    : effectiveSides ? checkUpperFloorSetbackSides(effectiveSides, lengthMm, widthMm) : null;
  const setbackInvalid = setbackEnabled && (sidesProblem !== null || (!perSideSetback && upperFloorSetbackMm > 0 && (
    lengthMm - 2 * upperFloorSetbackMm < 2_000
    || widthMm - 2 * upperFloorSetbackMm < 2_000
  )));

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
          upper_floor_setback_mm: effectiveUpperInset,
          upper_floor_setback_sides_mm: effectiveSides
            ? { x_min_mm: effectiveSides.xMinMm, x_max_mm: effectiveSides.xMaxMm, y_min_mm: effectiveSides.yMinMm, y_max_mm: effectiveSides.yMaxMm }
            : null,
          upper_floor_setbacks_mm: perFloorSides
            ? perFloorSides.map((sides) => ({ x_min_mm: sides.xMinMm, x_max_mm: sides.xMaxMm, y_min_mm: sides.yMinMm, y_max_mm: sides.yMaxMm }))
            : null,
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
              : winderTurn
                ? {
                    kind: "winder_turn",
                    width_mm: stairWidthMm,
                    tread_depth_mm: treadDepthMm,
                    lower_step_count: winderLowerSteps,
                    upper_step_count: winderUpperSteps,
                    newel_mm: newelMm,
                    turn: stairTurn,
                    placement: stairPlacement,
                    railing: false,
                    material_id: stairMaterialId || null,
                  }
              : spiralStair
                ? {
                    kind: "spiral",
                    diameter_mm: spiralDiameterMm,
                    post_diameter_mm: spiralPostDiameterMm,
                    step_count: spiralSteps,
                    sweep_deg: spiralSweepDeg,
                    turn: stairTurn,
                    placement: stairPlacement,
                    railing: false,
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
          <NumberField label={ru ? "Отступ верхних этажей, мм" : "Upper-floor setback, mm"} value={effectiveUpperInset} min={0} max={10_000} step={100} onChange={setUpperFloorSetbackMm} disabled={!setbackEnabled || perSideSetback} />
        </div>
        {setbackEnabled && (
          <fieldset className="card stack">
            <legend>{ru ? "Отступ верхних этажей по сторонам" : "Per-side upper-floor setback"}</legend>
            <label className="check">
              <input type="checkbox" checked={perSideSetback} onChange={(event) => setPerSideSetback(event.target.checked)} />
              {ru ? "Задать отступ каждой стены отдельно (терраса, балкон)" : "Set each wall's setback separately (terrace, balcony)"}
            </label>
            {perSideSetback && (floors === 3
              ? [
                  { sides: setbackSides, setSides: setSetbackSides, title: ru ? "Этаж 2" : "Floor 2" },
                  { sides: topFloorSides, setSides: setTopFloorSides, title: ru ? "Этаж 3 и крыша" : "Floor 3 and roof" },
                ]
              : [{ sides: setbackSides, setSides: setSetbackSides, title: ru ? "Верхний этаж и крыша" : "Upper floor and roof" }]
            ).map(({ sides, setSides, title }) => (
              <div key={title} className="stack">
                <strong>{title}</strong>
                <div className="house-dimensions">
                  <NumberField label={ru ? "От стены X = 0, мм" : "From wall X = 0, mm"} value={sides.xMinMm} min={0} max={10_000} step={100} onChange={(value) => setSides((current) => ({ ...current, xMinMm: value }))} />
                  <NumberField label={ru ? "От стены X = длина, мм" : "From wall X = length, mm"} value={sides.xMaxMm} min={0} max={10_000} step={100} onChange={(value) => setSides((current) => ({ ...current, xMaxMm: value }))} />
                  <NumberField label={ru ? "От левой стены (Y = 0), мм" : "From left wall (Y = 0), mm"} value={sides.yMinMm} min={0} max={10_000} step={100} onChange={(value) => setSides((current) => ({ ...current, yMinMm: value }))} />
                  <NumberField label={ru ? "От правой стены (Y = ширина), мм" : "From right wall (Y = width), mm"} value={sides.yMaxMm} min={0} max={10_000} step={100} onChange={(value) => setSides((current) => ({ ...current, yMaxMm: value }))} />
                </div>
                <p className="muted">{ru
                  ? `${title}: ${(lengthMm - sides.xMinMm - sides.xMaxMm).toLocaleString(language)} × ${(widthMm - sides.yMinMm - sides.yMaxMm).toLocaleString(language)} мм.`
                  : `${title}: ${(lengthMm - sides.xMinMm - sides.xMaxMm).toLocaleString(language)} × ${(widthMm - sides.yMinMm - sides.yMaxMm).toLocaleString(language)} mm.`}</p>
              </div>
            ))}
            {perSideSetback && (
              <p className="muted">{ru
                ? "Отступы считаются от стен первого этажа; каждый верхний этаж стоит внутри нижнего. Это геометрия, а не расчёт консолей или опор."
                : "Setbacks are measured from the ground-floor walls; each upper floor stands inside the one below. This is geometry, not a cantilever or support calculation."}</p>
            )}
            {sidesProblem && <div className="error" role="alert">{upperFloorSetbackProblemText(sidesProblem)[language]}</div>}
          </fieldset>
        )}
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
                      { id: "winder_turn", glyph: "◣", ru: "Забежная, 90°", en: "Winder turn, 90°" },
                      { id: "spiral", glyph: "◉", ru: "Винтовая", en: "Spiral" },
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
                  {!spiralStair && (
                    <>
                      <NumberField label={ru ? "Ширина марша, мм" : "Flight width, mm"} value={stairWidthMm} min={700} max={2_000} step={50} onChange={setStairWidthMm} />
                      <NumberField label={ru ? "Глубина ступени, мм" : "Tread depth, mm"} value={treadDepthMm} min={200} max={400} step={10} onChange={setTreadDepthMm} />
                    </>
                  )}
                  {spiralStair ? (
                    <>
                      <NumberField label={ru ? "Диаметр лестницы, мм" : "Stair diameter, mm"} value={spiralDiameterMm} min={1_400} max={3_200} step={50} onChange={setSpiralDiameterMm} />
                      <NumberField label={ru ? "Диаметр столба, мм" : "Post diameter, mm"} value={spiralPostDiameterMm} min={100} max={300} step={10} onChange={setSpiralPostDiameterMm} />
                      <NumberField label={ru ? "Количество ступеней" : "Step count"} value={spiralSteps} min={10} max={20} step={1} onChange={setSpiralSteps} />
                      <NumberField label={ru ? "Суммарный поворот, °" : "Total sweep, °"} value={spiralSweepDeg} min={180} max={330} step={5} onChange={setSpiralSweepDeg} />
                      <label>
                        <span>{ru ? "Направление подъёма" : "Climb direction"}</span>
                        <select className="input" value={stairTurn} onChange={(event) => setStairTurn(event.target.value as typeof stairTurn)}>
                          <option value="left">{ru ? "Против часовой стрелки" : "Counter-clockwise"}</option>
                          <option value="right">{ru ? "По часовой стрелке" : "Clockwise"}</option>
                        </select>
                      </label>
                    </>
                  ) : lTurn ? (
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
                  ) : winderTurn ? (
                    <>
                      <NumberField label={ru ? "Ступеней в нижнем марше" : "Lower flight steps"} value={winderLowerSteps} min={3} max={24} step={1} onChange={setWinderLowerSteps} />
                      <NumberField label={ru ? "Ступеней в верхнем марше" : "Upper flight steps"} value={winderUpperSteps} min={3} max={24} step={1} onChange={setWinderUpperSteps} />
                      <NumberField label={ru ? "Внутренний просвет, мм" : "Newel void, mm"} value={newelMm} min={200} max={500} step={10} onChange={setNewelMm} />
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
                  {!winderTurn && !spiralStair && (
                    <label className="check">
                      <input type="checkbox" checked={railing} onChange={(event) => setRailing(event.target.checked)} />
                      {ru ? "Ограждение" : "Railing"}
                    </label>
                  )}
                </div>
                <p className="house-total">
                  {ru ? "Подъём / проступь / длина" : "Rise / tread / run"}: <strong>{riserMm.toFixed(1)} / {(spiralStair ? spiral.goingMm : treadDepthMm).toFixed(0)} / {stairRunMm.toFixed(0)} {ru ? "мм" : "mm"}</strong>
                  {spiralStair && (
                    <>
                      {" · "}{spiral.treadAngleDeg.toFixed(1)}° {ru ? "на ступень" : "per tread"}
                      {" · "}{ru ? "чистая ширина" : "clear width"} {spiral.clearWidthMm.toFixed(0)} {ru ? "мм" : "mm"}
                      {" · "}{riserCount} {ru ? "подъёмов" : "risers"}
                    </>
                  )}
                  {turningFootprint && (
                    <>
                      {" · "}{winderTurn
                        ? `${ru ? "3 забежные по линии хода" : "3 winders, walking-line going"} ${winder.winderGoingMm.toFixed(0)}`
                        : `${ru ? "площадка" : "landing"} ${stairWidthMm.toFixed(0)}×${(stairWidthMm * (uTurn ? 2 : 1)).toFixed(0)}`}
                      {" · "}{ru ? "габарит" : "footprint"} <strong>{turningFootprint.x.toFixed(0)}×{turningFootprint.y.toFixed(0)} {ru ? "мм" : "mm"}</strong>
                      {" · "}{riserCount} {ru ? "подъёмов" : "risers"}
                    </>
                  )}
                </p>
                {riseInvalid && <div className="error" role="alert">{ru
                  ? "Измените число ступеней: высота ступени должна быть 120–220 мм."
                  : "Change the step count: rise must be 120–220 mm."}</div>}
                {turningProblem && !riseInvalid && <div className="error" role="alert">{turningProblem}</div>}
                {stairFitProblem && !turningProblem && !riseInvalid && <div className="error" role="alert">{stairFitProblem}</div>}
                {winderTurn ? <span className="muted">{ru
                  ? "Ровно три забежные ступени по 30° вокруг открытого внутреннего просвета; каждая считается подъёмом. Ограждение, столб, прочность и строительные нормы для этого поворота не моделируются."
                  : "Exactly three 30° winders around an open newel void; each counts as one riser. Railings, a newel post, structure and building codes are not modelled for this turn."}</span> : spiralStair ? <span className="muted">{ru
                  ? "Точные секторные ступени объединяются с центральным столбом; проём повторяет сектор подъёма. Винтовое ограждение, прочность и строительные нормы не моделируются."
                  : "Exact sector treads fuse to the central post; the opening follows the climbed sector. A helical railing, structure and building codes are not modelled."}</span> : turning && <span className="muted">{ru
                  ? `Площадка ${uTurn ? "соединяет два равных параллельных марша" : "квадратная (ширина марша)"} и считается одним подъёмом.`
                  : `The landing ${uTurn ? "joins two equal parallel flights" : "is square (one flight width)"} and counts as one riser.`}</span>}
              </>
            ) : null}
          </fieldset>
        )}
        {setbackInvalid && !sidesProblem && <div className="error" role="alert">{ru
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
