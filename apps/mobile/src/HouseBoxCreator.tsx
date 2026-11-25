import { checkSpiralStair, checkWinderStair, type HouseBoxBody, type PhysicalAiClient, SPIRAL_STAIR_PROBLEM_TEXT, WINDER_STAIR_PROBLEM_TEXT } from "@physical-ai/contracts";
import { useMemo, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { colors, styles } from "./theme";

type Shape = "rectangle" | "l_shape" | "t_shape";
type StairKind = "straight" | "l_turn" | "u_turn" | "winder_turn" | "spiral";

function millimetres(value: string): number {
  return Number(value.replace(",", ".")) * 1_000;
}

function numberValue(value: string): number {
  return Number(value.replace(",", "."));
}

function Choice<T extends string>({
  value,
  selected,
  label,
  disabled = false,
  onChange,
}: {
  value: T;
  selected: T;
  label: string;
  disabled?: boolean;
  onChange: (value: T) => void;
}) {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ checked: value === selected, disabled }}
      disabled={disabled}
      style={[
        styles.chip,
        value === selected && { borderColor: colors.accent, backgroundColor: colors.accentWash },
        disabled && { opacity: 0.45 },
      ]}
      onPress={() => onChange(value)}
    >
      <Text style={styles.chipText}>{label}</Text>
    </Pressable>
  );
}

/** Exact numeric mobile house creator backed by the same immutable house-box job as web. */
export function HouseBoxCreator({
  client,
  workspaceId,
  onCreated,
  onBack,
}: {
  client: PhysicalAiClient;
  workspaceId: string;
  onCreated: (projectId: string) => void;
  onBack: () => void;
}) {
  const [label, setLabel] = useState("Дом");
  const [lengthM, setLengthM] = useState("12");
  const [widthM, setWidthM] = useState("8");
  const [floorHeightM, setFloorHeightM] = useState("3");
  const [floors, setFloors] = useState<1 | 2 | 3>(2);
  const [shape, setShape] = useState<Shape>("rectangle");
  const [upperFloorSetbackMm, setUpperFloorSetbackMm] = useState("0");
  const [addStair, setAddStair] = useState(false);
  const [stairKind, setStairKind] = useState<StairKind>("straight");
  const [stairWidthMm, setStairWidthMm] = useState("1000");
  const [treadMm, setTreadMm] = useState("280");
  const [straightSteps, setStraightSteps] = useState("17");
  const [lowerSteps, setLowerSteps] = useState("8");
  const [upperSteps, setUpperSteps] = useState("8");
  const [uFlightSteps, setUFlightSteps] = useState("8");
  const [winderLowerSteps, setWinderLowerSteps] = useState("7");
  const [winderUpperSteps, setWinderUpperSteps] = useState("7");
  const [newelMm, setNewelMm] = useState("250");
  const [spiralDiameterMm, setSpiralDiameterMm] = useState("2200");
  const [spiralPostDiameterMm, setSpiralPostDiameterMm] = useState("200");
  const [spiralSteps, setSpiralSteps] = useState("15");
  const [spiralSweepDeg, setSpiralSweepDeg] = useState("300");
  const [turn, setTurn] = useState<"left" | "right">("left");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stairAllowed = floors > 1 && shape === "rectangle";
  const dimensions = useMemo(() => ({
    length: millimetres(lengthM),
    width: millimetres(widthM),
    floorHeight: millimetres(floorHeightM),
    stairWidth: numberValue(stairWidthMm),
    tread: numberValue(treadMm),
    straightSteps: numberValue(straightSteps),
    lowerSteps: numberValue(lowerSteps),
    upperSteps: numberValue(upperSteps),
    uFlightSteps: numberValue(uFlightSteps),
    winderLowerSteps: numberValue(winderLowerSteps),
    winderUpperSteps: numberValue(winderUpperSteps),
    newel: numberValue(newelMm),
    spiralDiameter: numberValue(spiralDiameterMm),
    spiralPostDiameter: numberValue(spiralPostDiameterMm),
    spiralSteps: numberValue(spiralSteps),
    spiralSweep: numberValue(spiralSweepDeg),
    upperFloorSetback: numberValue(upperFloorSetbackMm),
  }), [lengthM, widthM, floorHeightM, stairWidthMm, treadMm, straightSteps, lowerSteps, upperSteps, uFlightSteps, winderLowerSteps, winderUpperSteps, newelMm, spiralDiameterMm, spiralPostDiameterMm, spiralSteps, spiralSweepDeg, upperFloorSetbackMm]);

  const winder = useMemo(() => checkWinderStair({
    widthMm: dimensions.stairWidth,
    treadMm: dimensions.tread,
    lowerSteps: dimensions.winderLowerSteps,
    upperSteps: dimensions.winderUpperSteps,
    newelMm: dimensions.newel,
    placement: "center",
    houseLengthMm: dimensions.length,
    houseWidthMm: dimensions.width,
    floorHeightMm: dimensions.floorHeight,
    upperFloorSetbackMm: dimensions.upperFloorSetback,
  }), [dimensions]);

  const spiral = useMemo(() => checkSpiralStair({
    diameterMm: dimensions.spiralDiameter,
    postDiameterMm: dimensions.spiralPostDiameter,
    stepCount: dimensions.spiralSteps,
    sweepDeg: dimensions.spiralSweep,
    placement: "center",
    houseLengthMm: dimensions.length,
    houseWidthMm: dimensions.width,
    floorHeightMm: dimensions.floorHeight,
    upperFloorSetbackMm: dimensions.upperFloorSetback,
  }), [dimensions]);

  const stairProblem = useMemo(() => {
    if (!addStair || !stairAllowed) return null;
    if (stairKind === "winder_turn") {
      return winder.problem ? WINDER_STAIR_PROBLEM_TEXT[winder.problem].ru : null;
    }
    if (stairKind === "spiral") {
      return spiral.problem ? SPIRAL_STAIR_PROBLEM_TEXT[spiral.problem].ru : null;
    }
    const risers = stairKind === "straight"
      ? dimensions.straightSteps
      : stairKind === "l_turn"
        ? dimensions.lowerSteps + dimensions.upperSteps + 1
        : 2 * dimensions.uFlightSteps + 1;
    const rise = dimensions.floorHeight / risers;
    if (
      stairKind === "l_turn"
      && (!Number.isInteger(dimensions.lowerSteps)
        || !Number.isInteger(dimensions.upperSteps)
        || dimensions.lowerSteps < 3
        || dimensions.lowerSteps > 26
        || dimensions.upperSteps < 3
        || dimensions.upperSteps > 26)
    ) return "В каждом марше нужно 3–26 ступеней.";
    if (
      stairKind === "u_turn"
      && (!Number.isInteger(dimensions.uFlightSteps)
        || dimensions.uFlightSteps < 5
        || dimensions.uFlightSteps > 14)
    ) return "В каждом равном марше нужно 5–14 ступеней.";
    if (!Number.isInteger(risers) || risers < 10 || risers > 30) return "Нужно 10–30 подъёмов.";
    if (rise < 120 || rise > 220) return "Высота подъёма должна быть 120–220 мм.";
    if (stairKind !== "straight" && (2 * rise + dimensions.tread < 550 || 2 * rise + dimensions.tread > 700)) {
      return "Для поворотной лестницы 2 × подъём + проступь должно быть 550–700 мм.";
    }
    const footprintLength = stairKind === "straight"
      ? dimensions.tread * dimensions.straightSteps
      : stairKind === "l_turn"
        ? dimensions.tread * dimensions.lowerSteps + dimensions.stairWidth
        : dimensions.tread * dimensions.uFlightSteps + dimensions.stairWidth;
    const footprintWidth = stairKind === "straight"
      ? dimensions.stairWidth
      : stairKind === "l_turn"
        ? dimensions.stairWidth + dimensions.tread * dimensions.upperSteps
        : 2 * dimensions.stairWidth;
    if (
      footprintLength > dimensions.length - 2 * dimensions.upperFloorSetback - 700
      || footprintWidth > dimensions.width - 2 * dimensions.upperFloorSetback - 700
    ) return "Лестница и проёмы не помещаются с отступом 350 мм от стен.";
    return null;
  }, [addStair, stairAllowed, stairKind, dimensions, spiral, winder]);

  async function create() {
    if (busy) return;
    setError(null);
    const stairEnabled = addStair && stairAllowed;
    const baseDimensions = [dimensions.length, dimensions.width, dimensions.floorHeight];
    const stairDimensions = [
      dimensions.stairWidth,
      dimensions.tread,
      ...(stairKind === "straight"
        ? [dimensions.straightSteps]
        : stairKind === "l_turn"
          ? [dimensions.lowerSteps, dimensions.upperSteps]
          : stairKind === "winder_turn"
            ? [dimensions.winderLowerSteps, dimensions.winderUpperSteps, dimensions.newel]
            : stairKind === "spiral"
              ? [dimensions.spiralDiameter, dimensions.spiralPostDiameter, dimensions.spiralSteps, dimensions.spiralSweep]
            : [dimensions.uFlightSteps]),
    ];
    if (
      !label.trim()
      || baseDimensions.some((value) => !Number.isFinite(value))
      || dimensions.length < 2_000
      || dimensions.length > 50_000
      || dimensions.width < 2_000
      || dimensions.width > 50_000
      || dimensions.floorHeight < 2_200
      || dimensions.floorHeight > 6_000
      || !Number.isFinite(dimensions.upperFloorSetback)
      || dimensions.upperFloorSetback < 0
      || dimensions.upperFloorSetback > 10_000
      || (floors > 1 && shape === "rectangle" && dimensions.upperFloorSetback > 0 && (
        dimensions.length - 2 * dimensions.upperFloorSetback < 2_000
        || dimensions.width - 2 * dimensions.upperFloorSetback < 2_000
      ))
      || (stairEnabled && (
        stairDimensions.some((value) => !Number.isFinite(value))
        || (stairKind !== "spiral" && (
          dimensions.stairWidth < 700
          || dimensions.stairWidth > 2_000
          || dimensions.tread < 200
          || dimensions.tread > 400
        ))
        || stairProblem !== null
      ))
    ) {
      setError(stairProblem ?? "Проверьте размеры: дом 2–50 м, этаж 2,2–6 м, марш 700–2000 мм.");
      return;
    }
    const stair: HouseBoxBody["stair"] = !stairEnabled
      ? null
      : stairKind === "straight"
        ? {
            kind: "straight",
            width_mm: dimensions.stairWidth,
            tread_depth_mm: dimensions.tread,
            step_count: dimensions.straightSteps,
            placement: "center",
            railing: true,
            material_id: null,
          }
        : stairKind === "l_turn"
          ? {
            kind: "l_turn",
            width_mm: dimensions.stairWidth,
            tread_depth_mm: dimensions.tread,
            lower_step_count: dimensions.lowerSteps,
            upper_step_count: dimensions.upperSteps,
            turn,
            placement: "center",
            railing: true,
            material_id: null,
          }
          : stairKind === "winder_turn"
            ? {
                kind: "winder_turn",
                width_mm: dimensions.stairWidth,
                tread_depth_mm: dimensions.tread,
                lower_step_count: dimensions.winderLowerSteps,
                upper_step_count: dimensions.winderUpperSteps,
                newel_mm: dimensions.newel,
                turn,
                placement: "center",
                railing: false,
                material_id: null,
              }
            : stairKind === "spiral"
              ? {
                  kind: "spiral",
                  diameter_mm: dimensions.spiralDiameter,
                  post_diameter_mm: dimensions.spiralPostDiameter,
                  step_count: dimensions.spiralSteps,
                  sweep_deg: dimensions.spiralSweep,
                  turn,
                  placement: "center",
                  railing: false,
                  material_id: null,
                }
            : {
              kind: "u_turn",
              width_mm: dimensions.stairWidth,
              tread_depth_mm: dimensions.tread,
              flight_step_count: dimensions.uFlightSteps,
              turn,
              placement: "center",
              railing: true,
              material_id: null,
            };
    setBusy(true);
    try {
      const accepted = await client.buildHouseBox(
        {
          workspace_id: workspaceId,
          label: label.trim(),
          length_mm: dimensions.length,
          width_mm: dimensions.width,
          floor_height_mm: dimensions.floorHeight,
          floors,
          shape,
          stair,
          upper_floor_setback_mm: floors > 1 && shape === "rectangle" ? dimensions.upperFloorSetback : 0,
        },
        `mobile-house-box-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      );
      const job = await client.waitForJob(accepted.job.job_id, { intervalMs: 1_000 });
      if (job.status !== "succeeded") {
        throw new Error((job.error as { message?: string } | null)?.message ?? "Дом не построен");
      }
      onCreated(accepted.project_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBusy(false);
    }
  }

  return (
    <View style={{ gap: 12 }}>
      <Text style={styles.heading}>Дом по параметрам</Text>
      <Text style={styles.muted}>
        Сервер строит точные immutable shell каждого этажа, отдельную плоскую крышу и выбранную лестницу. Строительные нормы и произвольные контуры не рассчитываются.
      </Text>
      <TextInput style={styles.input} value={label} maxLength={200} editable={!busy} onChangeText={setLabel} placeholder="Название" placeholderTextColor={colors.muted} />
      <View style={styles.row} accessibilityRole="radiogroup">
        <Choice value="rectangle" selected={shape} label="Прямоугольник" disabled={busy} onChange={setShape} />
        <Choice value="l_shape" selected={shape} label="Г-форма" disabled={busy} onChange={(value) => { setShape(value); setAddStair(false); }} />
        <Choice value="t_shape" selected={shape} label="Т-форма" disabled={busy} onChange={(value) => { setShape(value); setAddStair(false); }} />
      </View>
      {floors > 1 && shape === "rectangle" ? (
        <TextInput style={styles.input} value={upperFloorSetbackMm} editable={!busy} onChangeText={setUpperFloorSetbackMm} keyboardType="number-pad" placeholder="Отступ верхних этажей, мм" placeholderTextColor={colors.muted} accessibilityLabel="Симметричный отступ верхних этажей в миллиметрах" />
      ) : null}
      <View style={styles.row}>
        <TextInput style={[styles.input, { flex: 1 }]} value={lengthM} editable={!busy} onChangeText={setLengthM} keyboardType="decimal-pad" placeholder="Длина, м" placeholderTextColor={colors.muted} accessibilityLabel="Длина дома в метрах" />
        <TextInput style={[styles.input, { flex: 1 }]} value={widthM} editable={!busy} onChangeText={setWidthM} keyboardType="decimal-pad" placeholder="Ширина, м" placeholderTextColor={colors.muted} accessibilityLabel="Ширина дома в метрах" />
        <TextInput style={[styles.input, { flex: 1 }]} value={floorHeightM} editable={!busy} onChangeText={setFloorHeightM} keyboardType="decimal-pad" placeholder="Этаж, м" placeholderTextColor={colors.muted} accessibilityLabel="Высота этажа в метрах" />
      </View>
      <View style={styles.row} accessibilityRole="radiogroup">
        {([1, 2, 3] as const).map((count) => (
          <Pressable key={count} accessibilityRole="radio" accessibilityState={{ checked: floors === count }} disabled={busy} style={[styles.chip, floors === count && { borderColor: colors.accent, backgroundColor: colors.accentWash }]} onPress={() => { setFloors(count); if (count === 1) setAddStair(false); }}>
            <Text style={styles.chipText}>{count} эт.</Text>
          </Pressable>
        ))}
      </View>
      {stairAllowed ? (
        <>
          <Pressable style={[styles.chip, addStair && { borderColor: colors.accent, backgroundColor: colors.accentWash }]} disabled={busy} onPress={() => setAddStair((value) => !value)} accessibilityRole="checkbox" accessibilityState={{ checked: addStair }}>
            <Text style={styles.chipText}>Добавить точную лестницу и проёмы</Text>
          </Pressable>
          {addStair ? (
            <View style={[styles.card, { gap: 10 }]}>
              <View style={styles.row} accessibilityRole="radiogroup">
                <Choice value="straight" selected={stairKind} label="Прямая" disabled={busy} onChange={setStairKind} />
                <Choice value="l_turn" selected={stairKind} label="Г-образная" disabled={busy} onChange={setStairKind} />
                <Choice value="u_turn" selected={stairKind} label="П-образная" disabled={busy} onChange={setStairKind} />
                <Choice value="winder_turn" selected={stairKind} label="Забежная 90°" disabled={busy} onChange={setStairKind} />
                <Choice value="spiral" selected={stairKind} label="Винтовая" disabled={busy} onChange={setStairKind} />
              </View>
              {stairKind !== "spiral" ? (
                <View style={styles.row}>
                  <TextInput style={[styles.input, { flex: 1 }]} value={stairWidthMm} editable={!busy} onChangeText={setStairWidthMm} keyboardType="number-pad" placeholder="Марш, мм" placeholderTextColor={colors.muted} />
                  <TextInput style={[styles.input, { flex: 1 }]} value={treadMm} editable={!busy} onChangeText={setTreadMm} keyboardType="number-pad" placeholder="Проступь, мм" placeholderTextColor={colors.muted} />
                </View>
              ) : null}
              {stairKind === "spiral" ? (
                <>
                  <View style={styles.row}>
                    <TextInput style={[styles.input, { flex: 1 }]} value={spiralDiameterMm} editable={!busy} onChangeText={setSpiralDiameterMm} keyboardType="number-pad" placeholder="Диаметр, мм" placeholderTextColor={colors.muted} accessibilityLabel="Диаметр винтовой лестницы" />
                    <TextInput style={[styles.input, { flex: 1 }]} value={spiralPostDiameterMm} editable={!busy} onChangeText={setSpiralPostDiameterMm} keyboardType="number-pad" placeholder="Столб, мм" placeholderTextColor={colors.muted} accessibilityLabel="Диаметр центрального столба" />
                  </View>
                  <View style={styles.row}>
                    <TextInput style={[styles.input, { flex: 1 }]} value={spiralSteps} editable={!busy} onChangeText={setSpiralSteps} keyboardType="number-pad" placeholder="Ступеней" placeholderTextColor={colors.muted} />
                    <TextInput style={[styles.input, { flex: 1 }]} value={spiralSweepDeg} editable={!busy} onChangeText={setSpiralSweepDeg} keyboardType="number-pad" placeholder="Поворот, °" placeholderTextColor={colors.muted} />
                  </View>
                  <View style={styles.row} accessibilityRole="radiogroup">
                    <Choice value="left" selected={turn} label="Против часовой" disabled={busy} onChange={setTurn} />
                    <Choice value="right" selected={turn} label="По часовой" disabled={busy} onChange={setTurn} />
                  </View>
                  {spiral.problem ? null : (
                    <Text style={styles.muted}>
                      {`${dimensions.spiralSteps} подъёмов по ${spiral.riseMm.toFixed(1)} мм · ${spiral.treadAngleDeg.toFixed(1)}° на ступень · проступь по линии хода ${spiral.goingMm.toFixed(0)} мм`}
                    </Text>
                  )}
                  <Text style={styles.muted}>
                    Точные секторные ступени объединяются с центральным столбом. Винтовое ограждение, прочность и строительные нормы не моделируются.
                  </Text>
                </>
              ) : stairKind === "straight" ? (
                <TextInput style={styles.input} value={straightSteps} editable={!busy} onChangeText={setStraightSteps} keyboardType="number-pad" placeholder="Подъёмов" placeholderTextColor={colors.muted} />
              ) : stairKind === "l_turn" ? (
                <>
                  <View style={styles.row}>
                    <TextInput style={[styles.input, { flex: 1 }]} value={lowerSteps} editable={!busy} onChangeText={setLowerSteps} keyboardType="number-pad" placeholder="Нижний марш" placeholderTextColor={colors.muted} />
                    <TextInput style={[styles.input, { flex: 1 }]} value={upperSteps} editable={!busy} onChangeText={setUpperSteps} keyboardType="number-pad" placeholder="Верхний марш" placeholderTextColor={colors.muted} />
                  </View>
                  <View style={styles.row} accessibilityRole="radiogroup">
                    <Choice value="left" selected={turn} label="Поворот налево" disabled={busy} onChange={setTurn} />
                    <Choice value="right" selected={turn} label="Поворот направо" disabled={busy} onChange={setTurn} />
                  </View>
                </>
              ) : stairKind === "winder_turn" ? (
                <>
                  <View style={styles.row}>
                    <TextInput style={[styles.input, { flex: 1 }]} value={winderLowerSteps} editable={!busy} onChangeText={setWinderLowerSteps} keyboardType="number-pad" placeholder="Нижний марш" placeholderTextColor={colors.muted} accessibilityLabel="Ступеней в нижнем марше" />
                    <TextInput style={[styles.input, { flex: 1 }]} value={winderUpperSteps} editable={!busy} onChangeText={setWinderUpperSteps} keyboardType="number-pad" placeholder="Верхний марш" placeholderTextColor={colors.muted} accessibilityLabel="Ступеней в верхнем марше" />
                    <TextInput style={[styles.input, { flex: 1 }]} value={newelMm} editable={!busy} onChangeText={setNewelMm} keyboardType="number-pad" placeholder="Просвет, мм" placeholderTextColor={colors.muted} accessibilityLabel="Внутренний просвет в миллиметрах" />
                  </View>
                  <View style={styles.row} accessibilityRole="radiogroup">
                    <Choice value="left" selected={turn} label="Поворот налево" disabled={busy} onChange={setTurn} />
                    <Choice value="right" selected={turn} label="Поворот направо" disabled={busy} onChange={setTurn} />
                  </View>
                  {winder.problem ? null : (
                    <Text style={styles.muted}>
                      {`${winder.riserCount} подъёмов по ${winder.riseMm.toFixed(1)} мм · габарит ${winder.footprint.x.toFixed(0)}×${winder.footprint.y.toFixed(0)} мм · забежная по линии хода ${winder.winderGoingMm.toFixed(0)} мм`}
                    </Text>
                  )}
                  <Text style={styles.muted}>
                    Ровно три забежные ступени вокруг открытого просвета. Ограждение, столб, прочность и нормы для этого поворота не моделируются.
                  </Text>
                </>
              ) : (
                <>
                  <TextInput style={styles.input} value={uFlightSteps} editable={!busy} onChangeText={setUFlightSteps} keyboardType="number-pad" placeholder="Ступеней в каждом марше" placeholderTextColor={colors.muted} />
                  <View style={styles.row} accessibilityRole="radiogroup">
                    <Choice value="left" selected={turn} label="Разворот налево" disabled={busy} onChange={setTurn} />
                    <Choice value="right" selected={turn} label="Разворот направо" disabled={busy} onChange={setTurn} />
                  </View>
                </>
              )}
              {stairProblem ? <Text style={styles.error}>{stairProblem}</Text> : null}
            </View>
          ) : null}
        </>
      ) : (
        <Text style={styles.muted}>Лестницы пока доступны только для прямоугольного дома в 2–3 этажа.</Text>
      )}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <View style={styles.row}>
        <Pressable style={styles.button} disabled={busy} onPress={onBack}><Text style={styles.buttonText}>← Назад</Text></Pressable>
        <Pressable style={[styles.button, styles.buttonPrimary, busy && { opacity: 0.5 }]} disabled={busy} onPress={() => void create()}><Text style={styles.buttonText}>{busy ? "Строим…" : "Создать точный дом"}</Text></Pressable>
      </View>
    </View>
  );
}
