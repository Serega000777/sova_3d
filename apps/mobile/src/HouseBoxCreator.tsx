import { type HouseBoxBody, type PhysicalAiClient } from "@physical-ai/contracts";
import { useMemo, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { colors, styles } from "./theme";

type Shape = "rectangle" | "l_shape" | "t_shape";
type StairKind = "straight" | "l_turn";

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
  const [addStair, setAddStair] = useState(false);
  const [stairKind, setStairKind] = useState<StairKind>("straight");
  const [stairWidthMm, setStairWidthMm] = useState("1000");
  const [treadMm, setTreadMm] = useState("280");
  const [straightSteps, setStraightSteps] = useState("17");
  const [lowerSteps, setLowerSteps] = useState("8");
  const [upperSteps, setUpperSteps] = useState("8");
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
  }), [lengthM, widthM, floorHeightM, stairWidthMm, treadMm, straightSteps, lowerSteps, upperSteps]);

  const stairProblem = useMemo(() => {
    if (!addStair || !stairAllowed) return null;
    const risers = stairKind === "straight"
      ? dimensions.straightSteps
      : dimensions.lowerSteps + dimensions.upperSteps + 1;
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
    if (!Number.isInteger(risers) || risers < 10 || risers > 30) return "Нужно 10–30 подъёмов.";
    if (rise < 120 || rise > 220) return "Высота подъёма должна быть 120–220 мм.";
    if (stairKind === "l_turn" && (2 * rise + dimensions.tread < 550 || 2 * rise + dimensions.tread > 700)) {
      return "Для Г-лестницы 2 × подъём + проступь должно быть 550–700 мм.";
    }
    return null;
  }, [addStair, stairAllowed, stairKind, dimensions]);

  async function create() {
    if (busy) return;
    setError(null);
    const stairEnabled = addStair && stairAllowed;
    const baseDimensions = [dimensions.length, dimensions.width, dimensions.floorHeight];
    const stairDimensions = [
      dimensions.stairWidth,
      dimensions.tread,
      dimensions.straightSteps,
      dimensions.lowerSteps,
      dimensions.upperSteps,
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
      || (stairEnabled && (
        stairDimensions.some((value) => !Number.isFinite(value))
        || dimensions.stairWidth < 700
        || dimensions.stairWidth > 2_000
        || dimensions.tread < 200
        || dimensions.tread > 400
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
        : {
            kind: "l_turn",
            width_mm: dimensions.stairWidth,
            tread_depth_mm: dimensions.tread,
            lower_step_count: dimensions.lowerSteps,
            upper_step_count: dimensions.upperSteps,
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
              </View>
              <View style={styles.row}>
                <TextInput style={[styles.input, { flex: 1 }]} value={stairWidthMm} editable={!busy} onChangeText={setStairWidthMm} keyboardType="number-pad" placeholder="Марш, мм" placeholderTextColor={colors.muted} />
                <TextInput style={[styles.input, { flex: 1 }]} value={treadMm} editable={!busy} onChangeText={setTreadMm} keyboardType="number-pad" placeholder="Проступь, мм" placeholderTextColor={colors.muted} />
              </View>
              {stairKind === "straight" ? (
                <TextInput style={styles.input} value={straightSteps} editable={!busy} onChangeText={setStraightSteps} keyboardType="number-pad" placeholder="Подъёмов" placeholderTextColor={colors.muted} />
              ) : (
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
