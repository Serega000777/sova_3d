import type { Axis, SketchConstraint, Vec2, Vec3 } from "@physical-ai/contracts";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

type Kind = "loft" | "sweep" | "revolve";
type Direction = "free" | "horizontal" | "vertical";
type DraftPoint = [string, string];

export type ExactSketchOperation = { type: Kind; [key: string]: unknown };

const DEFAULT_POINTS: DraftPoint[] = [
  ["0", "0"],
  ["20", "0.4"],
  ["20.2", "10"],
  ["0.2", "9.8"],
];

function numeric(value: string): number {
  return Number(value.replace(",", "."));
}

function Field({
  label,
  value,
  onChange,
  width = 112,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  width?: number;
}) {
  return (
    <View style={{ width, gap: 4 }}>
      <Text style={styles.muted}>{label}</Text>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChange}
        keyboardType="decimal-pad"
        selectTextOnFocus
      />
    </View>
  );
}

function axisFrame(axis: Axis): { normal: Vec3; xDirection: Vec3 } {
  if (axis === "x") return { normal: [1, 0, 0], xDirection: [0, 1, 0] };
  if (axis === "y") return { normal: [0, 1, 0], xDirection: [1, 0, 0] };
  return { normal: [0, 0, 1], xDirection: [1, 0, 0] };
}

function parsePath(value: string): Vec3[] | null {
  const rows = value
    .split(/\n+/)
    .filter((row) => row.trim())
    .map((row) => row.split(/[,;\s]+/).filter(Boolean).map(Number));
  if (
    rows.length < 2 ||
    rows.some((point) => point.length !== 3 || point.some((coordinate) => !Number.isFinite(coordinate)))
  ) {
    return null;
  }
  const path = rows as Vec3[];
  if (
    path.slice(1).some((point, index) =>
      point.every((coordinate, coordinateIndex) => coordinate === path[index][coordinateIndex]),
    )
  ) {
    return null;
  }
  return path;
}

export function ExactSketchSheet({
  visible,
  language,
  busy,
  blockedReason,
  error,
  onClose,
  onApply,
}: {
  visible: boolean;
  language: "ru" | "en";
  busy: boolean;
  blockedReason: string | null;
  error: string | null;
  onClose: () => void;
  onApply: (operation: ExactSketchOperation, combine: "add" | "cut", label: string) => void;
}) {
  const ru = language === "ru";
  const [kind, setKind] = useState<Kind>("loft");
  const [combine, setCombine] = useState<"add" | "cut">("add");
  const [points, setPoints] = useState<DraftPoint[]>(DEFAULT_POINTS);
  const [directions, setDirections] = useState<Direction[]>([
    "horizontal",
    "vertical",
    "horizontal",
    "vertical",
  ]);
  const [exactEdges, setExactEdges] = useState([true, true, true, true]);
  const [lengths, setLengths] = useState(["20", "10", "20", "10"]);
  const [fixFirst, setFixFirst] = useState(true);
  const [axis, setAxis] = useState<Axis>("z");
  const [origin, setOrigin] = useState<[string, string, string]>(["0", "0", "0"]);
  const [loftHeight, setLoftHeight] = useState("30");
  const [loftScale, setLoftScale] = useState("0.5");
  const [loftRuled, setLoftRuled] = useState(false);
  const [pathText, setPathText] = useState("0, 0, 0\n0, 0, 30\n20, 0, 50");
  const [angle, setAngle] = useState("360");

  const result = useMemo((): { operation: ExactSketchOperation | null; issue: string | null } => {
    const parsedPoints = points.map(([x, y]) => [numeric(x), numeric(y)] as Vec2);
    if (parsedPoints.length < 3 || parsedPoints.some((point) => point.some((value) => !Number.isFinite(value)))) {
      return { operation: null, issue: ru ? "Эскизу нужны минимум три корректные точки." : "The sketch needs at least three valid points." };
    }
    const constraints: SketchConstraint[] = fixFirst ? [{ kind: "fixed", point: 0 }] : [];
    for (let index = 0; index < parsedPoints.length; index += 1) {
      const end = (index + 1) % parsedPoints.length;
      const direction = directions[index] ?? "free";
      if (direction !== "free") constraints.push({ kind: direction, start: index, end });
      if (exactEdges[index]) {
        const length = numeric(lengths[index] ?? "");
        if (!Number.isFinite(length) || length <= 0) {
          return { operation: null, issue: ru ? "Точная длина ребра должна быть больше нуля." : "An exact edge length must be positive." };
        }
        constraints.push({ kind: "distance", start: index, end, distance_mm: length });
      }
    }
    const profile = {
      kind: "sketch" as const,
      points_mm: parsedPoints,
      segments: parsedPoints.map(() => ({ kind: "line" as const })),
      constraints,
      tolerance_mm: 1e-5,
    };
    const originMm = origin.map(numeric) as Vec3;
    if (originMm.some((value) => !Number.isFinite(value))) {
      return { operation: null, issue: ru ? "Начало координат должно быть числовым." : "Origin coordinates must be numeric." };
    }
    if (kind === "sweep") {
      const path = parsePath(pathText);
      return path
        ? { operation: { type: "sweep", profile, path_mm: path }, issue: null }
        : { operation: null, issue: ru ? "Путь sweep: минимум две разные строки X, Y, Z." : "Sweep path needs at least two distinct X, Y, Z rows." };
    }
    if (kind === "revolve") {
      const angleDeg = numeric(angle);
      if (parsedPoints.some(([radius]) => radius < 0) || !Number.isFinite(angleDeg) || angleDeg <= 0 || angleDeg > 360) {
        return { operation: null, issue: ru ? "Для revolve X — неотрицательный радиус, угол — от 0 до 360°." : "Revolve needs non-negative X radii and an angle in (0, 360]." };
      }
      return { operation: { type: "revolve", profile, axis, angle_deg: angleDeg, origin_mm: originMm }, issue: null };
    }
    const height = numeric(loftHeight);
    const scale = numeric(loftScale);
    if (!Number.isFinite(height) || height <= 0 || !Number.isFinite(scale) || scale <= 0) {
      return { operation: null, issue: ru ? "Высота и масштаб loft должны быть больше нуля." : "Loft height and scale must be positive." };
    }
    const { normal, xDirection } = axisFrame(axis);
    const topOrigin = originMm.map((value, index) => value + normal[index] * height) as Vec3;
    const topProfile = {
      ...profile,
      points_mm: parsedPoints.map(([x, y]) => [x * scale, y * scale] as Vec2),
      constraints: constraints.map((constraint) =>
        constraint.kind === "distance"
          ? { ...constraint, distance_mm: constraint.distance_mm * scale }
          : constraint,
      ),
    };
    return {
      operation: {
        type: "loft",
        sections: [
          { profile, origin_mm: originMm, normal, x_direction: xDirection },
          { profile: topProfile, origin_mm: topOrigin, normal, x_direction: xDirection },
        ],
        ruled: loftRuled,
      },
      issue: null,
    };
  }, [angle, axis, directions, exactEdges, fixFirst, kind, lengths, loftHeight, loftRuled, loftScale, origin, pathText, points, ru]);

  function updatePoint(index: number, coordinate: 0 | 1, value: string) {
    setPoints((current) =>
      current.map((point, item) => item === index ? point.map((part, axisIndex) => axisIndex === coordinate ? value : part) as DraftPoint : point),
    );
  }

  function addPoint() {
    const last = points.at(-1) ?? ["0", "0"];
    const nextX = numeric(last[0]);
    setPoints((current) => [...current, [Number.isFinite(nextX) ? String(nextX + 10) : "10", last[1]]]);
    setDirections((current) => [...current, "free"]);
    setExactEdges((current) => [...current, false]);
    setLengths((current) => [...current, "10"]);
  }

  function removePoint(index: number) {
    if (points.length <= 3) return;
    setPoints((current) => current.filter((_, item) => item !== index));
    setDirections((current) => current.filter((_, item) => item !== index));
    setExactEdges((current) => current.filter((_, item) => item !== index));
    setLengths((current) => current.filter((_, item) => item !== index));
  }

  const labels: Record<Kind, string> = { loft: "Loft", sweep: "Sweep", revolve: "Revolve" };

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="90%"
      tabletWidth={620}
      accessibilityLabel={ru ? "Закрыть точный эскиз" : "Close exact sketch"}
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.heading}>{ru ? "Точный эскиз и тело" : "Exact sketch and solid"}</Text>
        <Pressable onPress={onClose} hitSlop={12}>
          <Text style={[styles.title, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>
      <Text style={styles.muted}>
        {ru
          ? "Точки — начальное приближение. B-Rep-ядро решает ограничения и отклоняет противоречивый эскиз."
          : "Points are the initial guess. The B-Rep kernel solves constraints and rejects conflicts."}
      </Text>
      <ScrollView contentContainerStyle={{ gap: 12 }} keyboardShouldPersistTaps="handled">
        <View style={styles.row}>
          {(["loft", "sweep", "revolve"] as const).map((item) => (
            <Pressable key={item} style={[styles.chip, kind === item && { borderColor: colors.accent }]} onPress={() => setKind(item)}>
              <Text style={[styles.chipText, kind === item && { color: colors.accent }]}>{labels[item]}</Text>
            </Pressable>
          ))}
        </View>
        <Pressable style={[styles.chip, fixFirst && { borderColor: colors.selection }, { alignSelf: "flex-start" }]} onPress={() => setFixFirst((value) => !value)}>
          <Text style={[styles.chipText, fixFirst && { color: colors.selection }]}>
            {ru ? "Зафиксировать P0" : "Fix P0"} · {fixFirst ? (ru ? "да" : "on") : ru ? "нет" : "off"}
          </Text>
        </Pressable>
        {points.map((point, index) => {
          const direction = directions[index] ?? "free";
          return (
            <View key={index} style={[styles.card, { padding: 10 }]}>
              <View style={styles.row}>
                <Text style={styles.heading}>P{index}</Text>
                <Field label="X, мм" value={point[0]} onChange={(value) => updatePoint(index, 0, value)} />
                <Field label="Y, мм" value={point[1]} onChange={(value) => updatePoint(index, 1, value)} />
                <Pressable style={[styles.chip, points.length <= 3 && { opacity: 0.45 }]} disabled={points.length <= 3} onPress={() => removePoint(index)}>
                  <Text style={styles.chipText}>−</Text>
                </Pressable>
              </View>
              <Text style={styles.muted}>P{index} → P{(index + 1) % points.length}</Text>
              <View style={styles.row}>
                {(["free", "horizontal", "vertical"] as const).map((item) => (
                  <Pressable key={item} style={[styles.chip, direction === item && { borderColor: colors.selection }]} onPress={() => setDirections((current) => current.map((value, row) => row === index ? item : value))}>
                    <Text style={[styles.chipText, direction === item && { color: colors.selection }]}>
                      {item === "free" ? (ru ? "свободно" : "free") : item === "horizontal" ? (ru ? "горизонталь" : "horizontal") : ru ? "вертикаль" : "vertical"}
                    </Text>
                  </Pressable>
                ))}
                <Pressable style={[styles.chip, exactEdges[index] && { borderColor: colors.accent }]} onPress={() => setExactEdges((current) => current.map((value, row) => row === index ? !value : value))}>
                  <Text style={[styles.chipText, exactEdges[index] && { color: colors.accent }]}>{ru ? "точная длина" : "exact length"}</Text>
                </Pressable>
                {exactEdges[index] ? <Field label={ru ? "Длина, мм" : "Length, mm"} value={lengths[index] ?? ""} onChange={(value) => setLengths((current) => current.map((part, row) => row === index ? value : part))} /> : null}
              </View>
            </View>
          );
        })}
        <Pressable style={styles.button} onPress={addPoint}><Text style={styles.buttonText}>+ {ru ? "Точка" : "Point"}</Text></Pressable>

        {kind === "loft" ? (
          <View style={styles.row}>
            <Field label={ru ? "Высота, мм" : "Height, mm"} value={loftHeight} onChange={setLoftHeight} />
            <Field label={ru ? "Масштаб верха" : "Top scale"} value={loftScale} onChange={setLoftScale} />
            <Pressable style={[styles.chip, loftRuled && { borderColor: colors.selection }]} onPress={() => setLoftRuled((value) => !value)}>
              <Text style={[styles.chipText, loftRuled && { color: colors.selection }]}>{ru ? "Линейчатый loft" : "Ruled loft"}</Text>
            </Pressable>
          </View>
        ) : null}
        {kind === "sweep" ? (
          <View style={{ gap: 4 }}>
            <Text style={styles.muted}>{ru ? "Путь: одна точка X, Y, Z на строку" : "Path: one X, Y, Z point per row"}</Text>
            <TextInput style={[styles.input, styles.mono, { minHeight: 112, textAlignVertical: "top" }]} multiline value={pathText} onChangeText={setPathText} />
          </View>
        ) : null}
        {kind === "revolve" ? <Field label={ru ? "Угол, °" : "Angle, °"} value={angle} onChange={setAngle} /> : null}

        {kind !== "sweep" ? (
          <>
            <Text style={styles.muted}>{ru ? "Ось построения" : "Construction axis"}</Text>
            <View style={styles.row}>
              {(["x", "y", "z"] as const).map((item) => (
                <Pressable key={item} style={[styles.chip, axis === item && { borderColor: colors.selection }]} onPress={() => setAxis(item)}>
                  <Text style={[styles.chipText, axis === item && { color: colors.selection }]}>{item.toUpperCase()}</Text>
                </Pressable>
              ))}
            </View>
            <Text style={styles.muted}>{ru ? "Начало X/Y/Z, мм" : "Origin X/Y/Z, mm"}</Text>
            <View style={styles.row}>
              {([0, 1, 2] as const).map((index) => <Field key={index} label={"XYZ"[index]} value={origin[index]} onChange={(value) => setOrigin((current) => current.map((part, item) => item === index ? value : part) as [string, string, string])} />)}
            </View>
          </>
        ) : null}
        <View style={styles.row}>
          {(["add", "cut"] as const).map((item) => (
            <Pressable key={item} style={[styles.chip, combine === item && { borderColor: colors.accent2 }]} onPress={() => setCombine(item)}>
              <Text style={[styles.chipText, combine === item && { color: colors.accent2 }]}>{item === "add" ? (ru ? "Добавить" : "Add") : ru ? "Вырезать" : "Cut"}</Text>
            </Pressable>
          ))}
        </View>
        {result.issue ? <Text style={styles.error}>{result.issue}</Text> : null}
        {blockedReason ? <Text style={styles.error}>{blockedReason}</Text> : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <View style={styles.row}>
          <Pressable
            style={[styles.button, styles.buttonPrimary, (!result.operation || blockedReason || busy) && { opacity: 0.45 }]}
            disabled={!result.operation || Boolean(blockedReason) || busy}
            onPress={() => result.operation && onApply(result.operation, combine, `${labels[kind]} constrained sketch`)}
          >
            <Text style={styles.buttonText}>{busy ? (ru ? "Строим…" : "Building…") : ru ? "Построить точное тело" : "Build exact solid"}</Text>
          </Pressable>
          <Pressable style={styles.button} disabled={busy} onPress={onClose}><Text style={styles.buttonText}>{ru ? "Отмена" : "Cancel"}</Text></Pressable>
        </View>
      </ScrollView>
    </SheetShell>
  );
}
