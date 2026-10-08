"use client";

import type { CadProfileSeed, SketchConstraint, SketchSegment, Vec2, Vec3 } from "@physical-ai/contracts";
import { useEffect, useMemo, useState } from "react";

type ExactCadKind = "loft" | "sweep" | "revolve" | "nurbs_surface";

export type ExactCadOperation = { type: ExactCadKind; [key: string]: unknown };

type Direction = "free" | "horizontal" | "vertical";
type SegmentKind = SketchSegment["kind"];

export function ExactCadPanel({
  language,
  busy,
  initialKind = "loft",
  initialProfile = null,
  replaceSource = false,
  onApply,
}: {
  language: "en" | "ru";
  busy: boolean;
  initialKind?: Exclude<ExactCadKind, "nurbs_surface">;
  initialProfile?: CadProfileSeed | null;
  replaceSource?: boolean;
  onApply: (
    operation: ExactCadOperation,
    combine: "add" | "cut",
    label: string,
  ) => Promise<void>;
}) {
  const ru = language === "ru";
  const [kind, setKind] = useState<ExactCadKind>(initialKind);
  const [combine, setCombine] = useState<"add" | "cut">("add");
  const [points, setPoints] = useState<Vec2[]>([
    [0, 0],
    [20, 0.4],
    [20.2, 10],
    [0.2, 9.8],
  ]);
  const [directions, setDirections] = useState<Direction[]>([
    "horizontal",
    "vertical",
    "horizontal",
    "vertical",
  ]);
  const [segmentKinds, setSegmentKinds] = useState<SegmentKind[]>(["line", "line", "line", "line"]);
  const [arcCenters, setArcCenters] = useState<Vec2[]>([
    [10, 0.2],
    [20.1, 5.2],
    [10.2, 9.9],
    [0.1, 4.9],
  ]);
  const [arcClockwise, setArcClockwise] = useState<boolean[]>([false, false, false, false]);
  const [splinePoints, setSplinePoints] = useState<string[]>([
    "10, -3",
    "24, 5",
    "10, 13",
    "-4, 5",
  ]);
  const [nurbsControlPoints, setNurbsControlPoints] = useState<string[]>([
    "10, -3",
    "24, 5",
    "10, 13",
    "-4, 5",
  ]);
  const [nurbsDegrees, setNurbsDegrees] = useState<number[]>([2, 2, 2, 2]);
  const [nurbsWeights, setNurbsWeights] = useState<string[]>(["1, 1, 1", "1, 1, 1", "1, 1, 1", "1, 1, 1"]);
  const [nurbsKnots, setNurbsKnots] = useState<string[]>(["0, 1", "0, 1", "0, 1", "0, 1"]);
  const [nurbsMultiplicities, setNurbsMultiplicities] = useState<string[]>(["3, 3", "3, 3", "3, 3", "3, 3"]);
  const [exactEdges, setExactEdges] = useState<boolean[]>([true, true, false, false]);
  const [lengths, setLengths] = useState<number[]>([20, 10, 20, 10]);
  const [fixFirst, setFixFirst] = useState(true);
  const [origin, setOrigin] = useState<Vec3>([0, 0, 0]);
  const [normal, setNormal] = useState<Vec3>([0, 0, 1]);
  const [xDirection, setXDirection] = useState<Vec3>([1, 0, 0]);
  const [loftHeight, setLoftHeight] = useState(30);
  const [loftScale, setLoftScale] = useState(0.5);
  const [loftRuled, setLoftRuled] = useState(false);
  const [pathText, setPathText] = useState("0, 0, 0\n0, 0, 30\n20, 0, 50");
  const [axis, setAxis] = useState<"x" | "y" | "z">("z");
  const [angle, setAngle] = useState(360);
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
  const [surfaceThickness, setSurfaceThickness] = useState(2);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!initialProfile) return;
    const seeded = initialProfile.profile.points_mm.map(([x, y]) => [x, y] as Vec2);
    const count = seeded.length;
    setPoints(seeded);
    setDirections(Array.from({ length: count }, () => "free" as const));
    setSegmentKinds(
      (initialProfile.profile.segments ?? seeded.map(() => ({ kind: "line" as const })))
        .map((segment) => segment.kind),
    );
    setArcCenters(seeded.map((point, index) => {
      const next = seeded[(index + 1) % count] as Vec2;
      return [(point[0] + next[0]) / 2, (point[1] + next[1]) / 2] as Vec2;
    }));
    setArcClockwise(Array.from({ length: count }, () => false));
    setSplinePoints(Array.from({ length: count }, () => ""));
    setNurbsControlPoints(Array.from({ length: count }, () => ""));
    setNurbsDegrees(Array.from({ length: count }, () => 2));
    setNurbsWeights(Array.from({ length: count }, () => "1, 1, 1"));
    setNurbsKnots(Array.from({ length: count }, () => "0, 1"));
    setNurbsMultiplicities(Array.from({ length: count }, () => "3, 3"));
    setExactEdges(Array.from({ length: count }, () => false));
    setLengths(seeded.map((point, index) => {
      const next = seeded[(index + 1) % count] as Vec2;
      return Math.hypot(next[0] - point[0], next[1] - point[1]);
    }));
    setFixFirst(false);
    setOrigin(initialProfile.origin_mm);
    setNormal(initialProfile.normal);
    setXDirection(initialProfile.x_direction);
    const end = initialProfile.origin_mm.map(
      (value, index) => value + initialProfile.normal[index] * 30,
    ) as Vec3;
    setPathText(`${initialProfile.origin_mm.join(", ")}\n${end.join(", ")}`);
    setError(null);
  }, [initialProfile]);

  const edgeCount = points.length;
  const constraints = useMemo<SketchConstraint[]>(() => {
    const result: SketchConstraint[] = fixFirst ? [{ kind: "fixed", point: 0 }] : [];
    for (let index = 0; index < edgeCount; index += 1) {
      if ((segmentKinds[index] ?? "line") !== "line") continue;
      const end = (index + 1) % edgeCount;
      const direction = directions[index] ?? "free";
      if (direction !== "free") result.push({ kind: direction, start: index, end });
      if (exactEdges[index]) {
        result.push({ kind: "distance", start: index, end, distance_mm: lengths[index] ?? 1 });
      }
    }
    return result;
  }, [directions, edgeCount, exactEdges, fixFirst, lengths, segmentKinds]);

  function updatePoint(index: number, axisIndex: 0 | 1, value: number) {
    setPoints((current) =>
      current.map((point, item) =>
        item === index
          ? (point.map((coordinate, coordinateIndex) =>
              coordinateIndex === axisIndex ? value : coordinate,
            ) as Vec2)
          : point,
      ),
    );
  }

  function addPoint() {
    const last = points.at(-1) ?? [0, 0];
    const added: Vec2 = [last[0] + 10, last[1]];
    setPoints((current) => [...current, [last[0] + 10, last[1]]]);
    setDirections((current) => [...current, "free"]);
    setSegmentKinds((current) => [...current, "line"]);
    setArcCenters((current) => [...current, [(last[0] + added[0]) / 2, (last[1] + added[1]) / 2]]);
    setArcClockwise((current) => [...current, false]);
    setSplinePoints((current) => [...current, `${(last[0] + added[0]) / 2}, ${last[1] - 3}`]);
    setNurbsControlPoints((current) => [...current, `${(last[0] + added[0]) / 2}, ${last[1] - 3}`]);
    setNurbsDegrees((current) => [...current, 2]);
    setNurbsWeights((current) => [...current, "1, 1, 1"]);
    setNurbsKnots((current) => [...current, "0, 1"]);
    setNurbsMultiplicities((current) => [...current, "3, 3"]);
    setExactEdges((current) => [...current, false]);
    setLengths((current) => [...current, 10]);
  }

  function removePoint(index: number) {
    if (points.length <= 3) return;
    setPoints((current) => current.filter((_, item) => item !== index));
    setDirections((current) => current.filter((_, item) => item !== index));
    setSegmentKinds((current) => current.filter((_, item) => item !== index));
    setArcCenters((current) => current.filter((_, item) => item !== index));
    setArcClockwise((current) => current.filter((_, item) => item !== index));
    setSplinePoints((current) => current.filter((_, item) => item !== index));
    setNurbsControlPoints((current) => current.filter((_, item) => item !== index));
    setNurbsDegrees((current) => current.filter((_, item) => item !== index));
    setNurbsWeights((current) => current.filter((_, item) => item !== index));
    setNurbsKnots((current) => current.filter((_, item) => item !== index));
    setNurbsMultiplicities((current) => current.filter((_, item) => item !== index));
    setExactEdges((current) => current.filter((_, item) => item !== index));
    setLengths((current) => current.filter((_, item) => item !== index));
  }

  function parseSplinePoints(index: number): Vec2[] {
    return (splinePoints[index] ?? "")
      .split(/\n+/)
      .map((line) => line.split(/[,;\s]+/).filter(Boolean).map(Number))
      .filter((point) => point.length > 0)
      .map((point) => point as Vec2);
  }

  function parseNurbsControls(index: number): Vec2[] {
    return (nurbsControlPoints[index] ?? "")
      .split(/\n+/)
      .map((line) => line.split(/[,;\s]+/).filter(Boolean).map(Number))
      .filter((point) => point.length > 0)
      .map((point) => point as Vec2);
  }

  function parseNumberList(value: string): number[] {
    return value.split(/[,;\s]+/).filter(Boolean).map(Number);
  }

  function parseSurfaceControlGrid(): Vec3[][] {
    return surfaceControls
      .split(/\n+/)
      .filter((row) => row.trim().length > 0)
      .map((row) =>
        row.split(";").map((point) => point.split(/[,\s]+/).filter(Boolean).map(Number) as Vec3),
      );
  }

  function parseSurfaceWeightGrid(): number[][] {
    return surfaceWeights
      .split(/\n+/)
      .filter((row) => row.trim().length > 0)
      .map((row) => parseNumberList(row));
  }

  function validSurfaceBasis(
    poleCount: number,
    degree: number,
    knots: number[],
    multiplicities: number[],
  ): boolean {
    return Number.isInteger(degree) && degree >= 1 && degree <= 5 && degree < poleCount
      && knots.length >= 2 && knots.length === multiplicities.length
      && knots.every((value) => Number.isFinite(value) && Math.abs(value) <= 1_000_000)
      && knots.slice(1).every((value, index) => knots[index] < value)
      && multiplicities.every((value) => Number.isInteger(value) && value >= 1 && value <= 6)
      && multiplicities[0] === degree + 1
      && multiplicities.at(-1) === degree + 1
      && multiplicities.slice(1, -1).every((value) => value <= degree)
      && multiplicities.reduce((sum, value) => sum + value, 0) === poleCount + degree + 1;
  }

  function sketchSegments(scale = 1): SketchSegment[] {
    return segmentKinds.map((segmentKind, index) => {
      if (segmentKind === "arc") {
        const center = arcCenters[index] ?? [0, 0];
        return {
          kind: "arc",
          center_mm: [center[0] * scale, center[1] * scale],
          clockwise: arcClockwise[index] ?? false,
        };
      }
      if (segmentKind === "spline") {
        return {
          kind: "spline",
          through_points_mm: parseSplinePoints(index).map(([x, y]) => [x * scale, y * scale]),
        };
      }
      if (segmentKind === "nurbs") {
        return {
          kind: "nurbs",
          control_points_mm: parseNurbsControls(index).map(([x, y]) => [x * scale, y * scale] as Vec2),
          degree: nurbsDegrees[index] ?? 2,
          weights: parseNumberList(nurbsWeights[index] ?? ""),
          knots: parseNumberList(nurbsKnots[index] ?? ""),
          multiplicities: parseNumberList(nurbsMultiplicities[index] ?? ""),
        };
      }
      return { kind: "line" };
    });
  }

  function profile(scale = 1) {
    return {
      kind: "sketch" as const,
      points_mm: points.map(([x, y]) => [x * scale, y * scale] as Vec2),
      segments: sketchSegments(scale),
      constraints: constraints.map((constraint) =>
        constraint.kind === "distance"
          ? { ...constraint, distance_mm: constraint.distance_mm * scale }
          : constraint,
      ),
      tolerance_mm: 1e-5,
    };
  }

  function parsePath(): Vec3[] {
    return pathText
      .split(/\n+/)
      .map((line) => line.split(/[,;\s]+/).filter(Boolean).map(Number))
      .filter((point) => point.length > 0)
      .map((point) => point as Vec3);
  }

  async function submit() {
    setError(null);
    if (kind === "nurbs_surface") {
      const controlPoints = parseSurfaceControlGrid();
      const weights = parseSurfaceWeightGrid();
      const uPoles = controlPoints.length;
      const vPoles = controlPoints[0]?.length ?? 0;
      const uKnots = parseNumberList(surfaceUKnots);
      const vKnots = parseNumberList(surfaceVKnots);
      const uMultiplicities = parseNumberList(surfaceUMultiplicities);
      const vMultiplicities = parseNumberList(surfaceVMultiplicities);
      const validGrid = uPoles >= 2 && uPoles <= 16 && vPoles >= 2 && vPoles <= 16
        && controlPoints.every((row) => row.length === vPoles
          && row.every((point) => point.length === 3 && point.every(Number.isFinite)))
        && weights.length === uPoles
        && weights.every((row) => row.length === vPoles
          && row.every((value) => Number.isFinite(value) && value > 0 && value <= 1_000_000));
      if (!validGrid
        || !validSurfaceBasis(uPoles, surfaceUDegree, uKnots, uMultiplicities)
        || !validSurfaceBasis(vPoles, surfaceVDegree, vKnots, vMultiplicities)
        || !Number.isFinite(surfaceThickness) || surfaceThickness <= 0) {
        setError(ru
          ? "NURBS surface: проверьте прямоугольные grids, U/V basis и толщину."
          : "NURBS surface: check the rectangular grids, U/V bases, and thickness.");
        return;
      }
      await onApply({
        type: "nurbs_surface",
        control_points_mm: controlPoints,
        weights,
        u_degree: surfaceUDegree,
        v_degree: surfaceVDegree,
        u_knots: uKnots,
        v_knots: vKnots,
        u_multiplicities: uMultiplicities,
        v_multiplicities: vMultiplicities,
        thickness_mm: surfaceThickness,
        tolerance_mm: 1e-5,
      }, combine, "Exact rational NURBS surface");
      return;
    }
    if (points.length < 3 || points.some((point) => point.some((value) => !Number.isFinite(value)))) {
      setError(ru ? "Эскизу нужны минимум три корректные точки." : "The sketch needs at least three valid points.");
      return;
    }
    if (constraints.some((constraint) => constraint.kind === "distance" && constraint.distance_mm <= 0)) {
      setError(ru ? "Длина ребра должна быть больше нуля." : "Edge lengths must be positive.");
      return;
    }
    if (kind === "loft") {
      const normalLength = Math.hypot(...normal);
      const xLength = Math.hypot(...xDirection);
      const alignment = normal.reduce((sum, value, index) => sum + value * xDirection[index], 0);
      if (normalLength <= 1e-9 || xLength <= 1e-9) {
        setError(ru ? "Нормаль и направление X должны быть ненулевыми." : "Normal and X direction must be nonzero.");
        return;
      }
      if (Math.abs(alignment / (normalLength * xLength)) > 1e-6) {
        setError(ru ? "Нормаль и направление X должны быть перпендикулярны." : "Normal and X direction must be perpendicular.");
        return;
      }
    }
    for (let index = 0; index < points.length; index += 1) {
      const segmentKind = segmentKinds[index] ?? "line";
      if (segmentKind === "arc") {
        const center = arcCenters[index] ?? [Number.NaN, Number.NaN];
        const end = points[(index + 1) % points.length];
        const startRadius = Math.hypot(points[index][0] - center[0], points[index][1] - center[1]);
        const endRadius = Math.hypot(end[0] - center[0], end[1] - center[1]);
        if (!center.every(Number.isFinite) || Math.min(startRadius, endRadius) <= 1e-5 || Math.abs(startRadius - endRadius) > 1e-5) {
          setError(ru ? `Дуга P${index}: центр должен задавать одинаковый ненулевой радиус.` : `Arc P${index}: the center must give both endpoints the same nonzero radius.`);
          return;
        }
      }
      if (segmentKind === "spline") {
        const through = parseSplinePoints(index);
        if (through.length < 1 || through.some((point) => point.length !== 2 || point.some((value) => !Number.isFinite(value)))) {
          setError(ru ? `Spline P${index}: минимум одна строка X, Y.` : `Spline P${index}: enter at least one X, Y row.`);
          return;
        }
      }
      if (segmentKind === "nurbs") {
        const controls = parseNurbsControls(index);
        const degree = nurbsDegrees[index] ?? 2;
        const weights = parseNumberList(nurbsWeights[index] ?? "");
        const knots = parseNumberList(nurbsKnots[index] ?? "");
        const multiplicities = parseNumberList(nurbsMultiplicities[index] ?? "");
        const poles = controls.length + 2;
        const valid = controls.length >= 1
          && controls.every((point) => point.length === 2 && point.every(Number.isFinite))
          && Number.isInteger(degree) && degree >= 1 && degree <= 5 && degree < poles
          && weights.length === poles && weights.every((value) => Number.isFinite(value) && value > 0 && value <= 1_000_000)
          && knots.length >= 2 && knots.length === multiplicities.length
          && knots.every((value) => Number.isFinite(value) && Math.abs(value) <= 1_000_000)
          && knots.slice(1).every((value, item) => knots[item] < value)
          && multiplicities.every((value) => Number.isInteger(value) && value >= 1 && value <= 6)
          && multiplicities[0] === degree + 1
          && multiplicities.at(-1) === degree + 1
          && multiplicities.slice(1, -1).every((value) => value <= degree)
          && multiplicities.reduce((sum, value) => sum + value, 0) === poles + degree + 1;
        if (!valid) {
          setError(ru ? `NURBS P${index}: проверьте poles, degree, weights, knots и multiplicities.` : `NURBS P${index}: check poles, degree, weights, knots and multiplicities.`);
          return;
        }
      }
    }
    let operation: ExactCadOperation;
    if (kind === "loft") {
      if (loftHeight <= 0 || loftScale <= 0) {
        setError(ru ? "Высота и масштаб loft должны быть больше нуля." : "Loft height and scale must be positive.");
        return;
      }
      operation = {
        type: "loft",
        sections: [
          { profile: profile(), origin_mm: origin, normal, x_direction: xDirection },
          {
            profile: profile(loftScale),
            origin_mm: origin.map((value, index) => value + normal[index] / Math.hypot(...normal) * loftHeight) as Vec3,
            normal,
            x_direction: xDirection,
          },
        ],
        ruled: loftRuled,
      };
    } else if (kind === "sweep") {
      const path = parsePath();
      if (path.length < 2 || path.some((point) => point.length !== 3 || point.some((value) => !Number.isFinite(value)))) {
        setError(ru ? "Путь sweep: минимум две строки X, Y, Z." : "Sweep path: at least two X, Y, Z rows.");
        return;
      }
      operation = { type: "sweep", profile: profile(), path_mm: path };
    } else {
      if (angle <= 0 || angle > 360 || points.some(([radius]) => radius < 0)) {
        setError(ru ? "Для revolve радиус X неотрицательный, угол — от 0 до 360°." : "Revolve needs non-negative X radii and an angle in (0, 360].");
        return;
      }
      operation = { type: "revolve", profile: profile(), axis, angle_deg: angle, origin_mm: origin };
    }
    await onApply(operation, combine, `${kind[0].toUpperCase()}${kind.slice(1)} constrained sketch`);
  }

  return (
    <div className="stack exact-cad-panel">
      <strong>{ru ? "Точный B-Rep: эскиз или поверхность" : "Exact B-Rep: sketch or surface"}</strong>
      {initialProfile && (
        <span className="status-green">
          {replaceSource
            ? ru
              ? `Профиль получен из ${initialProfile.source_faces} граней. Результат станет новой точной CAD-версией; исходный mesh останется в истории.`
              : `Profile derived from ${initialProfile.source_faces} faces. The result becomes a new exact CAD version; the source mesh stays in history.`
            : ru
              ? `Профиль получен из ${initialProfile.source_faces} выбранных граней; точки и плоскость можно править.`
              : `Profile derived from ${initialProfile.source_faces} selected faces; its points and plane remain editable.`}
        </span>
      )}
      <div className="segmented">
        {(["loft", "sweep", "revolve", "nurbs_surface"] as const).map((item) => (
          <button key={item} type="button" className={kind === item ? "active" : ""} onClick={() => setKind(item)}>
            {item === "nurbs_surface" ? "Surface" : item[0].toUpperCase() + item.slice(1)}
          </button>
        ))}
      </div>
      {kind !== "nurbs_surface" && <>
        <span className="muted">
        {ru
          ? "Точки — стартовое приближение. Ядро решает ограничения и отклоняет противоречивый эскиз."
          : "Points are the initial guess. The kernel solves constraints and rejects conflicts."}
        </span>
        <label className="row muted">
        <input type="checkbox" checked={fixFirst} onChange={(event) => setFixFirst(event.target.checked)} />
        {ru ? "Зафиксировать первую точку" : "Fix the first point"}
      </label>
      <div className="stack">
        {points.map((point, index) => {
          const edgeEnd = (index + 1) % points.length;
          return (
            <div className="card stack" key={index}>
              <div className="row">
                <b>P{index}</b>
                <label>X <input className="input mono" type="number" value={point[0]} onChange={(event) => updatePoint(index, 0, Number(event.target.value))} /></label>
                <label>Y <input className="input mono" type="number" value={point[1]} onChange={(event) => updatePoint(index, 1, Number(event.target.value))} /></label>
                <button className="btn" type="button" disabled={points.length <= 3} onClick={() => removePoint(index)}>−</button>
              </div>
              <div className="row muted">
                <span>P{index} → P{edgeEnd}</span>
                <select value={directions[index] ?? "free"} onChange={(event) => setDirections((current) => current.map((value, item) => item === index ? event.target.value as Direction : value))}>
                  <option value="free">{ru ? "свободно" : "free"}</option>
                  <option value="horizontal">{ru ? "горизонталь" : "horizontal"}</option>
                  <option value="vertical">{ru ? "вертикаль" : "vertical"}</option>
                </select>
                <label className="row">
                  <input type="checkbox" checked={exactEdges[index] ?? false} onChange={(event) => setExactEdges((current) => current.map((value, item) => item === index ? event.target.checked : value))} />
                  {ru ? "длина" : "length"}
                </label>
                {exactEdges[index] && <input className="input mono" type="number" min={0.001} step={0.1} value={lengths[index] ?? 1} onChange={(event) => setLengths((current) => current.map((value, item) => item === index ? Number(event.target.value) : value))} />}
              </div>
              <div className="row muted">
                <span>{ru ? "Сегмент" : "Segment"}</span>
                <select value={segmentKinds[index] ?? "line"} onChange={(event) => setSegmentKinds((current) => current.map((value, item) => item === index ? event.target.value as SegmentKind : value))}>
                  <option value="line">Line</option>
                  <option value="arc">Arc</option>
                  <option value="spline">Spline</option>
                  <option value="nurbs">NURBS</option>
                </select>
                {(segmentKinds[index] ?? "line") !== "line" && <span>{ru ? "Ограничения направления/длины применяются только к line." : "Direction/length constraints apply to line only."}</span>}
              </div>
              {segmentKinds[index] === "arc" && (
                <div className="row muted">
                  <label>CX <input className="input mono" type="number" value={arcCenters[index]?.[0] ?? 0} onChange={(event) => setArcCenters((current) => current.map((center, item) => item === index ? [Number(event.target.value), center[1]] : center))} /></label>
                  <label>CY <input className="input mono" type="number" value={arcCenters[index]?.[1] ?? 0} onChange={(event) => setArcCenters((current) => current.map((center, item) => item === index ? [center[0], Number(event.target.value)] : center))} /></label>
                  <label className="row"><input type="checkbox" checked={arcClockwise[index] ?? false} onChange={(event) => setArcClockwise((current) => current.map((value, item) => item === index ? event.target.checked : value))} />{ru ? "по часовой" : "clockwise"}</label>
                </div>
              )}
              {segmentKinds[index] === "spline" && (
                <label className="stack muted">
                  <span>{ru ? "Промежуточные точки spline: X, Y по одной на строку" : "Spline through-points: one X, Y row each"}</span>
                  <textarea className="input mono" rows={3} value={splinePoints[index] ?? ""} onChange={(event) => setSplinePoints((current) => current.map((value, item) => item === index ? event.target.value : value))} />
                </label>
              )}
              {segmentKinds[index] === "nurbs" && (
                <div className="stack muted">
                  <label className="stack">
                    <span>{ru ? "Внутренние control points: X, Y по одной на строку" : "Interior control points: one X, Y row each"}</span>
                    <textarea className="input mono" rows={3} value={nurbsControlPoints[index] ?? ""} onChange={(event) => setNurbsControlPoints((current) => current.map((value, item) => item === index ? event.target.value : value))} />
                  </label>
                  <div className="primitive-grid two">
                    <label>Degree<input className="input mono" type="number" min={1} max={5} step={1} value={nurbsDegrees[index] ?? 2} onChange={(event) => setNurbsDegrees((current) => current.map((value, item) => item === index ? Number(event.target.value) : value))} /></label>
                    <label>Weights<input className="input mono" value={nurbsWeights[index] ?? ""} onChange={(event) => setNurbsWeights((current) => current.map((value, item) => item === index ? event.target.value : value))} /></label>
                    <label>Knots<input className="input mono" value={nurbsKnots[index] ?? ""} onChange={(event) => setNurbsKnots((current) => current.map((value, item) => item === index ? event.target.value : value))} /></label>
                    <label>Multiplicities<input className="input mono" value={nurbsMultiplicities[index] ?? ""} onChange={(event) => setNurbsMultiplicities((current) => current.map((value, item) => item === index ? event.target.value : value))} /></label>
                  </div>
                </div>
              )}
            </div>
          );
        })}
        <button className="btn" type="button" onClick={addPoint}>+ {ru ? "Точка" : "Point"}</button>
        </div>
      </>}

      {kind === "nurbs_surface" && (
        <div className="stack card">
          <span className="muted">
            {ru
              ? "Каждая строка — U-ряд; V-точки X,Y,Z разделяются точкой с запятой. Весы имеют ту же сетку."
              : "Each line is a U row; separate V poles X,Y,Z with semicolons. Weights use the same grid."}
          </span>
          <label className="stack">
            <span>{ru ? "Control points, мм" : "Control points, mm"}</span>
            <textarea className="input mono" rows={5} value={surfaceControls} onChange={(event) => setSurfaceControls(event.target.value)} />
          </label>
          <label className="stack">
            <span>Weights</span>
            <textarea className="input mono" rows={4} value={surfaceWeights} onChange={(event) => setSurfaceWeights(event.target.value)} />
          </label>
          <div className="primitive-grid two">
            <label>U degree<input className="input mono" type="number" min={1} max={5} step={1} value={surfaceUDegree} onChange={(event) => setSurfaceUDegree(Number(event.target.value))} /></label>
            <label>V degree<input className="input mono" type="number" min={1} max={5} step={1} value={surfaceVDegree} onChange={(event) => setSurfaceVDegree(Number(event.target.value))} /></label>
            <label>U knots<input className="input mono" value={surfaceUKnots} onChange={(event) => setSurfaceUKnots(event.target.value)} /></label>
            <label>V knots<input className="input mono" value={surfaceVKnots} onChange={(event) => setSurfaceVKnots(event.target.value)} /></label>
            <label>U multiplicities<input className="input mono" value={surfaceUMultiplicities} onChange={(event) => setSurfaceUMultiplicities(event.target.value)} /></label>
            <label>V multiplicities<input className="input mono" value={surfaceVMultiplicities} onChange={(event) => setSurfaceVMultiplicities(event.target.value)} /></label>
            <label>{ru ? "Толщина, мм" : "Thickness, mm"}<input className="input mono" type="number" min={0.001} step={0.1} value={surfaceThickness} onChange={(event) => setSurfaceThickness(Number(event.target.value))} /></label>
          </div>
        </div>
      )}

      {kind === "loft" && (
        <>
          <div className="primitive-grid two">
            <label>{ru ? "Высота вдоль нормали, мм" : "Height along normal, mm"}<input className="input mono" type="number" min={0.001} value={loftHeight} onChange={(event) => setLoftHeight(Number(event.target.value))} /></label>
            <label>{ru ? "Масштаб верха" : "Top scale"}<input className="input mono" type="number" min={0.01} step={0.05} value={loftScale} onChange={(event) => setLoftScale(Number(event.target.value))} /></label>
            <label className="row muted"><input type="checkbox" checked={loftRuled} onChange={(event) => setLoftRuled(event.target.checked)} />{ru ? "Линейчатая поверхность" : "Ruled surface"}</label>
          </div>
          <span className="muted">{ru ? "Плоскость: нормаль и перпендикулярное направление локальной оси X." : "Plane: a normal and a perpendicular local X direction."}</span>
          <div className="primitive-grid three">
            {([0, 1, 2] as const).map((index) => <label key={`normal-${index}`}>N{"XYZ"[index]}<input className="input mono" type="number" step={0.1} value={normal[index]} onChange={(event) => setNormal((current) => current.map((value, item) => item === index ? Number(event.target.value) : value) as Vec3)} /></label>)}
          </div>
          <div className="primitive-grid three">
            {([0, 1, 2] as const).map((index) => <label key={`x-direction-${index}`}>X{"XYZ"[index]}<input className="input mono" type="number" step={0.1} value={xDirection[index]} onChange={(event) => setXDirection((current) => current.map((value, item) => item === index ? Number(event.target.value) : value) as Vec3)} /></label>)}
          </div>
        </>
      )}
      {kind === "sweep" && (
        <label className="stack">
          <span>{ru ? "Путь: одна точка X, Y, Z на строку" : "Path: one X, Y, Z point per row"}</span>
          <textarea className="input mono" rows={5} value={pathText} onChange={(event) => setPathText(event.target.value)} />
        </label>
      )}
      {kind === "revolve" && (
        <>
          <span className="muted">{ru ? "В эскизе X — радиус, Y — координата вдоль оси." : "Sketch X is radius; Y runs along the axis."}</span>
          <div className="segmented">{(["x", "y", "z"] as const).map((item) => <button key={item} type="button" className={axis === item ? "active" : ""} onClick={() => setAxis(item)}>{item.toUpperCase()}</button>)}</div>
          <label>{ru ? "Угол, °" : "Angle, °"}<input className="input mono" type="number" min={0.001} max={360} value={angle} onChange={(event) => setAngle(Number(event.target.value))} /></label>
        </>
      )}
      {kind !== "sweep" && kind !== "nurbs_surface" && (
        <div className="primitive-grid three">
          {([0, 1, 2] as const).map((index) => <label key={index}>{"XYZ"[index]}<input className="input mono" type="number" value={origin[index]} onChange={(event) => setOrigin((current) => current.map((value, item) => item === index ? Number(event.target.value) : value) as Vec3)} /></label>)}
        </div>
      )}
      {!replaceSource && (
        <div className="segmented">
          <button type="button" className={combine === "add" ? "active" : ""} onClick={() => setCombine("add")}>{ru ? "Добавить" : "Add"}</button>
          <button type="button" className={combine === "cut" ? "active" : ""} onClick={() => setCombine("cut")}>{ru ? "Вырезать" : "Cut"}</button>
        </div>
      )}
      {error && <div className="error">{error}</div>}
      <button className="btn primary" type="button" disabled={busy} onClick={() => void submit()}>
        {replaceSource
          ? (ru ? "Создать точную CAD-версию" : "Create exact CAD version")
          : (ru ? "Построить точное тело" : "Build exact body")}
      </button>
    </div>
  );
}
