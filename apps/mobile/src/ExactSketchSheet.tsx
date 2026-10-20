import {
  type Axis,
  type SketchConstraint,
  type SketchSegment,
  type Vec2,
  type Vec3,
} from "@physical-ai/contracts";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import {
  buildMobileSketchSegment,
  type MobileSketchSegmentKind,
  scaleMobileSketchSegment,
} from "./exact-sketch-curves";
import {
  buildMobileNurbsSurface,
  type MobileNurbsSurfaceOperation,
} from "./exact-nurbs-surface";
import {
  buildMobileSketchRelations,
  type MobileSketchRelationDraft,
  type MobileSketchRelationKind,
} from "./exact-sketch-relations";
import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

type Kind = "loft" | "sweep" | "revolve" | "nurbs_surface";
type Direction = "free" | "horizontal" | "vertical";
type DraftPoint = [string, string];

export type ExactSketchOperation =
  | MobileNurbsSurfaceOperation
  | { type: Exclude<Kind, "nurbs_surface">; [key: string]: unknown };

const DEFAULT_POINTS: DraftPoint[] = [
  ["0", "0"],
  ["20", "0.4"],
  ["20.2", "10"],
  ["0.2", "9.8"],
];

function midpoint(left: DraftPoint, right: DraftPoint): DraftPoint {
  const leftX = numeric(left[0]);
  const leftY = numeric(left[1]);
  const rightX = numeric(right[0]);
  const rightY = numeric(right[1]);
  return [String((leftX + rightX) / 2), String((leftY + rightY) / 2)];
}

function initialArcCenters(points: DraftPoint[]): DraftPoint[] {
  return points.map((point, index) => midpoint(point, points[(index + 1) % points.length]));
}

function numeric(value: string): number {
  return Number(value.replace(",", "."));
}

function Field({
  label,
  value,
  onChange,
  width = 112,
  keyboardType = "decimal-pad",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  width?: number;
  keyboardType?: "default" | "decimal-pad" | "number-pad" | "numbers-and-punctuation";
}) {
  return (
    <View style={{ width, gap: 4 }}>
      <Text style={styles.muted}>{label}</Text>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChange}
        keyboardType={keyboardType}
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
  const [segmentKinds, setSegmentKinds] = useState<MobileSketchSegmentKind[]>(DEFAULT_POINTS.map(() => "line"));
  const [arcCenters, setArcCenters] = useState<DraftPoint[]>(initialArcCenters(DEFAULT_POINTS));
  const [arcClockwise, setArcClockwise] = useState<boolean[]>(DEFAULT_POINTS.map(() => false));
  const [splinePoints, setSplinePoints] = useState<string[]>(DEFAULT_POINTS.map((point, index) => {
    const center = midpoint(point, DEFAULT_POINTS[(index + 1) % DEFAULT_POINTS.length]);
    return `${center[0]}, ${center[1]}`;
  }));
  const [nurbsControlPoints, setNurbsControlPoints] = useState<string[]>(DEFAULT_POINTS.map((point, index) => {
    const center = midpoint(point, DEFAULT_POINTS[(index + 1) % DEFAULT_POINTS.length]);
    return `${center[0]}, ${center[1]}`;
  }));
  const [nurbsDegrees, setNurbsDegrees] = useState<number[]>(DEFAULT_POINTS.map(() => 2));
  const [nurbsWeights, setNurbsWeights] = useState<string[]>(DEFAULT_POINTS.map(() => "1, 1, 1"));
  const [nurbsKnots, setNurbsKnots] = useState<string[]>(DEFAULT_POINTS.map(() => "0, 1"));
  const [nurbsMultiplicities, setNurbsMultiplicities] = useState<string[]>(DEFAULT_POINTS.map(() => "3, 3"));
  const [relations, setRelations] = useState<MobileSketchRelationDraft[]>([]);
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
  const [surfaceControls, setSurfaceControls] = useState(
    "10, 0, 0; 10, 0, 20\n10, 10, 0; 10, 10, 20\n0, 10, 0; 0, 10, 20",
  );
  const [surfaceWeights, setSurfaceWeights] = useState(
    "1, 1\n0.7071067811865476, 0.7071067811865476\n1, 1",
  );
  const [surfaceUDegree, setSurfaceUDegree] = useState(2);
  const [surfaceVDegree, setSurfaceVDegree] = useState(1);
  const [surfaceUKnots, setSurfaceUKnots] = useState("0, 1");
  const [surfaceVKnots, setSurfaceVKnots] = useState("0, 1");
  const [surfaceUMultiplicities, setSurfaceUMultiplicities] = useState("3, 3");
  const [surfaceVMultiplicities, setSurfaceVMultiplicities] = useState("2, 2");
  const [surfaceThickness, setSurfaceThickness] = useState("2");

  const result = useMemo((): { operation: ExactSketchOperation | null; issue: string | null } => {
    if (kind === "nurbs_surface") {
      const built = buildMobileNurbsSurface({
        controlPointsText: surfaceControls,
        weightsText: surfaceWeights,
        uDegree: surfaceUDegree,
        vDegree: surfaceVDegree,
        uKnotsText: surfaceUKnots,
        vKnotsText: surfaceVKnots,
        uMultiplicitiesText: surfaceUMultiplicities,
        vMultiplicitiesText: surfaceVMultiplicities,
        thicknessText: surfaceThickness,
      });
      const issues = {
        control_grid: ru
          ? "Контрольные точки должны образовывать прямоугольную сетку 2–16 × 2–16 из конечных X/Y/Z."
          : "Control points must form a finite 2–16 × 2–16 rectangular X/Y/Z grid.",
        weight_grid: ru
          ? "Сетка положительных весов должна точно совпадать с сеткой контрольных точек."
          : "The positive weight grid must exactly match the control-point grid.",
        u_basis: ru ? "Проверьте степень, узлы и кратности basis U." : "Check the U degree, knots, and multiplicities.",
        v_basis: ru ? "Проверьте степень, узлы и кратности basis V." : "Check the V degree, knots, and multiplicities.",
        collapsed_grid: ru
          ? "Контрольная сетка должна охватывать двумерную поверхность, а не одну линию."
          : "The control net must span a two-dimensional patch, not one line.",
        thickness: ru ? "Толщина должна быть в диапазоне (0, 10 000] мм." : "Thickness must be in (0, 10,000] mm.",
      } as const;
      return {
        operation: built.operation,
        issue: built.issue ? issues[built.issue] : null,
      };
    }
    const parsedPoints = points.map(([x, y]) => [numeric(x), numeric(y)] as Vec2);
    if (parsedPoints.length < 3 || parsedPoints.some((point) => point.some((value) => !Number.isFinite(value)))) {
      return { operation: null, issue: ru ? "Эскизу нужны минимум три корректные точки." : "The sketch needs at least three valid points." };
    }
    const segments: SketchSegment[] = [];
    for (let index = 0; index < parsedPoints.length; index += 1) {
      const draftCenter = arcCenters[index] ?? ["", ""];
      const center = draftCenter.map(numeric) as Vec2;
      const built = buildMobileSketchSegment({
        kind: segmentKinds[index] ?? "line",
        start: parsedPoints[index],
        end: parsedPoints[(index + 1) % parsedPoints.length],
        arcCenter: center,
        arcClockwise: arcClockwise[index] ?? false,
        splinePointsText: splinePoints[index] ?? "",
        nurbsControlPointsText: nurbsControlPoints[index] ?? "",
        nurbsDegree: nurbsDegrees[index] ?? 2,
        nurbsWeightsText: nurbsWeights[index] ?? "",
        nurbsKnotsText: nurbsKnots[index] ?? "",
        nurbsMultiplicitiesText: nurbsMultiplicities[index] ?? "",
      });
      if (!built.segment) {
        const detail = built.issue === "arc"
          ? (ru
              ? "центр должен задавать одинаковый ненулевой радиус"
              : "the center must give both endpoints the same non-zero radius")
          : built.issue === "spline"
            ? (ru
                ? "нужны 1–30 конечных различных промежуточных точек"
                : "enter 1–30 finite, consecutively distinct through-points")
            : (ru
                ? "проверьте 1–30 внутренних полюсов, степень, веса, узлы и кратности"
                : "check 1–30 interior poles, degree, weights, knots, and multiplicities");
        return {
          operation: null,
          issue: `${built.issue === "nurbs" ? "NURBS" : built.issue === "spline" ? "Spline" : ru ? "Дуга" : "Arc"} P${index} → P${(index + 1) % parsedPoints.length}: ${detail}.`,
        };
      }
      segments.push(built.segment);
    }
    const constraints: SketchConstraint[] = fixFirst ? [{ kind: "fixed", point: 0 }] : [];
    for (let index = 0; index < parsedPoints.length; index += 1) {
      const end = (index + 1) % parsedPoints.length;
      const direction = directions[index] ?? "free";
      if (segments[index]?.kind !== "line") continue;
      if (direction !== "free") constraints.push({ kind: direction, start: index, end });
      if (exactEdges[index]) {
        const length = numeric(lengths[index] ?? "");
        if (!Number.isFinite(length) || length <= 0) {
          return { operation: null, issue: ru ? "Точная длина ребра должна быть больше нуля." : "An exact edge length must be positive." };
        }
        constraints.push({ kind: "distance", start: index, end, distance_mm: length });
      }
    }
    const advanced = buildMobileSketchRelations(relations, parsedPoints.length, segments);
    if (!advanced.constraints) {
      return {
        operation: null,
        issue: ru
          ? `Связь ${advanced.issueIndex + 1}: нужны разные существующие точки или разные прямые рёбра без дубликатов.`
          : `Relation ${advanced.issueIndex + 1} needs distinct existing points or distinct line edges without duplicates.`,
      };
    }
    constraints.push(...advanced.constraints);
    const profile = {
      kind: "sketch" as const,
      points_mm: parsedPoints,
      segments,
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
      segments: segments.map((segment) => scaleMobileSketchSegment(segment, scale)),
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
  }, [angle, arcCenters, arcClockwise, axis, directions, exactEdges, fixFirst, kind, lengths, loftHeight, loftRuled, loftScale, nurbsControlPoints, nurbsDegrees, nurbsKnots, nurbsMultiplicities, nurbsWeights, origin, pathText, points, relations, ru, segmentKinds, splinePoints, surfaceControls, surfaceThickness, surfaceUDegree, surfaceUKnots, surfaceUMultiplicities, surfaceVDegree, surfaceVKnots, surfaceVMultiplicities, surfaceWeights]);

  function updatePoint(index: number, coordinate: 0 | 1, value: string) {
    setPoints((current) =>
      current.map((point, item) => item === index ? point.map((part, axisIndex) => axisIndex === coordinate ? value : part) as DraftPoint : point),
    );
  }

  function addPoint() {
    const last = points.at(-1) ?? ["0", "0"];
    const nextX = numeric(last[0]);
    const nextPoint: DraftPoint = [Number.isFinite(nextX) ? String(nextX + 10) : "10", last[1]];
    const previousLastIndex = points.length - 1;
    setPoints((current) => [...current, nextPoint]);
    setDirections((current) => [...current, "free"]);
    setSegmentKinds((current) => [
      ...current.map((value, index) => index === previousLastIndex ? "line" as const : value),
      "line",
    ]);
    setArcCenters((current) => [
      ...current.map((center, index) => index === previousLastIndex ? midpoint(last, nextPoint) : center),
      midpoint(nextPoint, points[0]),
    ]);
    setArcClockwise((current) => [
      ...current.map((value, index) => index === previousLastIndex ? false : value),
      false,
    ]);
    setSplinePoints((current) => [
      ...current.map((value, index) => index === previousLastIndex
        ? `${midpoint(last, nextPoint).join(", ")}`
        : value),
      `${midpoint(nextPoint, points[0]).join(", ")}`,
    ]);
    setNurbsControlPoints((current) => [
      ...current.map((value, index) => index === previousLastIndex
        ? `${midpoint(last, nextPoint).join(", ")}`
        : value),
      `${midpoint(nextPoint, points[0]).join(", ")}`,
    ]);
    setNurbsDegrees((current) => [...current, 2]);
    setNurbsWeights((current) => [...current, "1, 1, 1"]);
    setNurbsKnots((current) => [...current, "0, 1"]);
    setNurbsMultiplicities((current) => [...current, "3, 3"]);
    setExactEdges((current) => [...current, false]);
    setLengths((current) => [...current, "10"]);
  }

  function removePoint(index: number) {
    if (points.length <= 3) return;
    const nextPoints = points.filter((_, item) => item !== index);
    const predecessor = (index - 1 + nextPoints.length) % nextPoints.length;
    setPoints(nextPoints);
    setDirections((current) => current.filter((_, item) => item !== index));
    setSegmentKinds((current) => current
      .filter((_, item) => item !== index)
      .map((value, item) => item === predecessor ? "line" : value));
    setArcCenters((current) => current
      .filter((_, item) => item !== index)
      .map((center, item) => item === predecessor
        ? midpoint(nextPoints[predecessor], nextPoints[(predecessor + 1) % nextPoints.length])
        : center));
    setArcClockwise((current) => current
      .filter((_, item) => item !== index)
      .map((value, item) => item === predecessor ? false : value));
    const resetPredecessor = (current: string[]) => current
      .filter((_, item) => item !== index)
      .map((value, item) => item === predecessor
        ? `${midpoint(nextPoints[predecessor], nextPoints[(predecessor + 1) % nextPoints.length]).join(", ")}`
        : value);
    setSplinePoints(resetPredecessor);
    setNurbsControlPoints(resetPredecessor);
    setNurbsDegrees((current) => current.filter((_, item) => item !== index));
    setNurbsWeights((current) => current.filter((_, item) => item !== index));
    setNurbsKnots((current) => current.filter((_, item) => item !== index));
    setNurbsMultiplicities((current) => current.filter((_, item) => item !== index));
    setRelations([]);
    setExactEdges((current) => current.filter((_, item) => item !== index));
    setLengths((current) => current.filter((_, item) => item !== index));
  }

  const labels: Record<Kind, string> = {
    loft: "Loft",
    sweep: "Sweep",
    revolve: "Revolve",
    nurbs_surface: "NURBS surface",
  };

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
        {kind === "nurbs_surface"
          ? ru
            ? "Точная рациональная поверхность утолщается в замкнутое B-Rep-тело; периодические, обрезанные и multi-patch поверхности пока не поддерживаются."
            : "The exact rational surface is thickened into a closed B-Rep solid; periodic, trimmed, and multi-patch surfaces are not supported yet."
          : ru
            ? "Точки — начальное приближение. B-Rep-ядро решает ограничения и отклоняет противоречивый эскиз."
            : "Points are the initial guess. The B-Rep kernel solves constraints and rejects conflicts."}
      </Text>
      <ScrollView contentContainerStyle={{ gap: 12 }} keyboardShouldPersistTaps="handled">
        <View style={styles.row}>
          {(["loft", "sweep", "revolve", "nurbs_surface"] as const).map((item) => (
            <Pressable key={item} style={[styles.chip, kind === item && { borderColor: colors.accent }]} onPress={() => setKind(item)}>
              <Text style={[styles.chipText, kind === item && { color: colors.accent }]}>{labels[item]}</Text>
            </Pressable>
          ))}
        </View>
        {kind === "nurbs_surface" ? (
          <View style={[styles.card, { padding: 10, gap: 10 }]}>
            <Text style={styles.muted}>
              {ru
                ? "Каждая строка — U-ряд. V-точки X, Y, Z разделяются точкой с запятой; веса используют сетку того же размера."
                : "Each line is a U row. Separate V poles X, Y, Z with semicolons; weights use the same-sized grid."}
            </Text>
            <Text style={styles.muted}>{ru ? "Контрольные точки, мм" : "Control points, mm"}</Text>
            <TextInput
              style={[styles.input, styles.mono, { minHeight: 128, textAlignVertical: "top" }]}
              multiline
              value={surfaceControls}
              onChangeText={setSurfaceControls}
              keyboardType="numbers-and-punctuation"
            />
            <Text style={styles.muted}>{ru ? "Веса" : "Weights"}</Text>
            <TextInput
              style={[styles.input, styles.mono, { minHeight: 96, textAlignVertical: "top" }]}
              multiline
              value={surfaceWeights}
              onChangeText={setSurfaceWeights}
              keyboardType="numbers-and-punctuation"
            />
            <View style={styles.row}>
              <Field label={ru ? "Степень U" : "U degree"} value={String(surfaceUDegree)} onChange={(value) => setSurfaceUDegree(numeric(value))} keyboardType="number-pad" />
              <Field label={ru ? "Степень V" : "V degree"} value={String(surfaceVDegree)} onChange={(value) => setSurfaceVDegree(numeric(value))} keyboardType="number-pad" />
              <Field label={ru ? "Толщина, мм" : "Thickness, mm"} value={surfaceThickness} onChange={setSurfaceThickness} />
            </View>
            <View style={styles.row}>
              <Field label={ru ? "Узлы U" : "U knots"} value={surfaceUKnots} onChange={setSurfaceUKnots} width={180} keyboardType="numbers-and-punctuation" />
              <Field label={ru ? "Кратности U" : "U multiplicities"} value={surfaceUMultiplicities} onChange={setSurfaceUMultiplicities} width={180} keyboardType="numbers-and-punctuation" />
            </View>
            <View style={styles.row}>
              <Field label={ru ? "Узлы V" : "V knots"} value={surfaceVKnots} onChange={setSurfaceVKnots} width={180} keyboardType="numbers-and-punctuation" />
              <Field label={ru ? "Кратности V" : "V multiplicities"} value={surfaceVMultiplicities} onChange={setSurfaceVMultiplicities} width={180} keyboardType="numbers-and-punctuation" />
            </View>
          </View>
        ) : (
          <>
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
                {(["line", "arc", "spline", "nurbs"] as const).map((item) => (
                  <Pressable
                    key={item}
                    style={[styles.chip, (segmentKinds[index] ?? "line") === item && { borderColor: colors.accent2 }]}
                    onPress={() => {
                      setSegmentKinds((current) => current.map((value, row) => row === index ? item : value));
                      if (item === "arc") {
                        setArcCenters((current) => current.map((value, row) => row === index
                          ? midpoint(points[index], points[(index + 1) % points.length])
                          : value));
                      }
                      if (item !== "line") {
                        setDirections((current) => current.map((value, row) => row === index ? "free" : value));
                        setExactEdges((current) => current.map((value, row) => row === index ? false : value));
                      }
                    }}
                  >
                    <Text style={[styles.chipText, (segmentKinds[index] ?? "line") === item && { color: colors.accent2 }]}>
                      {item === "line"
                        ? (ru ? "Линия" : "Line")
                        : item === "arc"
                          ? (ru ? "Дуга" : "Arc")
                          : item === "spline"
                            ? "Spline"
                            : "NURBS"}
                    </Text>
                  </Pressable>
                ))}
                {(segmentKinds[index] ?? "line") === "arc" ? (
                  <>
                    <Field
                      label={ru ? "Центр X, мм" : "Centre X, mm"}
                      value={arcCenters[index]?.[0] ?? ""}
                      onChange={(value) => setArcCenters((current) => current.map((center, row) => row === index ? [value, center[1]] : center))}
                    />
                    <Field
                      label={ru ? "Центр Y, мм" : "Centre Y, mm"}
                      value={arcCenters[index]?.[1] ?? ""}
                      onChange={(value) => setArcCenters((current) => current.map((center, row) => row === index ? [center[0], value] : center))}
                    />
                    <Pressable
                      style={[styles.chip, arcClockwise[index] && { borderColor: colors.selection }]}
                      onPress={() => setArcClockwise((current) => current.map((value, row) => row === index ? !value : value))}
                    >
                      <Text style={[styles.chipText, arcClockwise[index] && { color: colors.selection }]}>
                        {arcClockwise[index] ? (ru ? "по часовой" : "clockwise") : (ru ? "против часовой" : "counter-clockwise")}
                      </Text>
                    </Pressable>
                  </>
                ) : null}
              </View>
              {(segmentKinds[index] ?? "line") === "spline" ? (
                <View style={{ gap: 4 }}>
                  <Text style={styles.muted}>
                    {ru ? "Промежуточные точки: X, Y по одной на строку" : "Through-points: one X, Y row each"}
                  </Text>
                  <TextInput
                    style={[styles.input, styles.mono, { minHeight: 80, textAlignVertical: "top" }]}
                    multiline
                    value={splinePoints[index] ?? ""}
                    onChangeText={(value) => setSplinePoints((current) => current.map((part, row) => row === index ? value : part))}
                  />
                </View>
              ) : null}
              {(segmentKinds[index] ?? "line") === "nurbs" ? (
                <View style={{ gap: 8 }}>
                  <Text style={styles.muted}>
                    {ru ? "Внутренние полюса: X, Y по одной на строку" : "Interior poles: one X, Y row each"}
                  </Text>
                  <TextInput
                    style={[styles.input, styles.mono, { minHeight: 80, textAlignVertical: "top" }]}
                    multiline
                    value={nurbsControlPoints[index] ?? ""}
                    onChangeText={(value) => setNurbsControlPoints((current) => current.map((part, row) => row === index ? value : part))}
                  />
                  <View style={styles.row}>
                    <Field label={ru ? "Степень" : "Degree"} value={String(nurbsDegrees[index] ?? 2)} onChange={(value) => setNurbsDegrees((current) => current.map((part, row) => row === index ? numeric(value) : part))} />
                    <Field label={ru ? "Веса" : "Weights"} value={nurbsWeights[index] ?? ""} onChange={(value) => setNurbsWeights((current) => current.map((part, row) => row === index ? value : part))} width={180} keyboardType="numbers-and-punctuation" />
                    <Field label={ru ? "Узлы" : "Knots"} value={nurbsKnots[index] ?? ""} onChange={(value) => setNurbsKnots((current) => current.map((part, row) => row === index ? value : part))} width={180} keyboardType="numbers-and-punctuation" />
                    <Field label={ru ? "Кратности" : "Multiplicities"} value={nurbsMultiplicities[index] ?? ""} onChange={(value) => setNurbsMultiplicities((current) => current.map((part, row) => row === index ? value : part))} width={180} keyboardType="numbers-and-punctuation" />
                  </View>
                </View>
              ) : null}
              {(segmentKinds[index] ?? "line") === "line" ? <View style={styles.row}>
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
              </View> : (
                <Text style={styles.muted}>
                  {ru ? "Ограничения направления и длины применяются только к прямой." : "Direction and length constraints apply to line segments only."}
                </Text>
              )}
            </View>
          );
        })}
        <Pressable style={styles.button} onPress={addPoint}><Text style={styles.buttonText}>+ {ru ? "Точка" : "Point"}</Text></Pressable>

        <View style={[styles.card, { padding: 10, gap: 8 }]}>
          <Text style={styles.heading}>{ru ? "Дополнительные связи" : "Advanced relations"}</Text>
          <Text style={styles.muted}>
            {ru
              ? "Совпадение использует номера точек P. Равенство, параллельность и перпендикулярность используют номера прямых рёбер Pn → Pn+1. Максимум 16 связей."
              : "Coincident uses point P indices. Equal, parallel, and perpendicular use line-edge indices Pn → Pn+1. Up to 16 relations."}
          </Text>
          {relations.map((relation, relationIndex) => (
            <View key={relationIndex} style={{ gap: 8 }}>
              <View style={styles.row}>
                {(["coincident", "equal_length", "parallel", "perpendicular"] as const).map((item) => {
                  const names: Record<MobileSketchRelationKind, string> = {
                    coincident: ru ? "Совпадение" : "Coincident",
                    equal_length: ru ? "Равная длина" : "Equal length",
                    parallel: ru ? "Параллельно" : "Parallel",
                    perpendicular: ru ? "Перпендикулярно" : "Perpendicular",
                  };
                  return (
                    <Pressable
                      key={item}
                      style={[styles.chip, relation.kind === item && { borderColor: colors.selection }]}
                      onPress={() => setRelations((current) => current.map((value, index) => index === relationIndex ? { ...value, kind: item } : value))}
                    >
                      <Text style={[styles.chipText, relation.kind === item && { color: colors.selection }]}>{names[item]}</Text>
                    </Pressable>
                  );
                })}
              </View>
              <View style={styles.row}>
                <Field
                  label={relation.kind === "coincident" ? (ru ? "Первая точка P" : "First point P") : (ru ? "Первое ребро P" : "First edge P")}
                  value={relation.first}
                  onChange={(value) => setRelations((current) => current.map((part, index) => index === relationIndex ? { ...part, first: value } : part))}
                  keyboardType="number-pad"
                />
                <Field
                  label={relation.kind === "coincident" ? (ru ? "Вторая точка P" : "Second point P") : (ru ? "Второе ребро P" : "Second edge P")}
                  value={relation.second}
                  onChange={(value) => setRelations((current) => current.map((part, index) => index === relationIndex ? { ...part, second: value } : part))}
                  keyboardType="number-pad"
                />
                <Pressable style={styles.chip} onPress={() => setRelations((current) => current.filter((_, index) => index !== relationIndex))}>
                  <Text style={styles.chipText}>{ru ? "Удалить" : "Remove"}</Text>
                </Pressable>
              </View>
            </View>
          ))}
          <Pressable
            style={[styles.button, relations.length >= 16 && { opacity: 0.45 }]}
            disabled={relations.length >= 16}
            onPress={() => setRelations((current) => [...current, { kind: "equal_length", first: "0", second: points.length > 2 ? "2" : "1" }])}
          >
            <Text style={styles.buttonText}>+ {ru ? "Связь" : "Relation"}</Text>
          </Pressable>
        </View>

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
          </>
        )}
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
            onPress={() => result.operation && onApply(
              result.operation,
              combine,
              kind === "nurbs_surface" ? "Exact rational NURBS surface" : `${labels[kind]} constrained sketch`,
            )}
          >
            <Text style={styles.buttonText}>{busy ? (ru ? "Строим…" : "Building…") : ru ? "Построить точное тело" : "Build exact solid"}</Text>
          </Pressable>
          <Pressable style={styles.button} disabled={busy} onPress={onClose}><Text style={styles.buttonText}>{ru ? "Отмена" : "Cancel"}</Text></Pressable>
        </View>
      </ScrollView>
    </SheetShell>
  );
}
