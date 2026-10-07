"use client";

import type { SketchConstraint, SketchSegment, Vec2, Vec3 } from "@physical-ai/contracts";
import { useMemo, useState } from "react";

export type ExactCadOperation = { type: "loft" | "sweep" | "revolve"; [key: string]: unknown };

type Direction = "free" | "horizontal" | "vertical";
type SegmentKind = SketchSegment["kind"];

export function ExactCadPanel({
  language,
  busy,
  initialKind = "loft",
  onApply,
}: {
  language: "en" | "ru";
  busy: boolean;
  initialKind?: "loft" | "sweep" | "revolve";
  onApply: (
    operation: ExactCadOperation,
    combine: "add" | "cut",
    label: string,
  ) => Promise<void>;
}) {
  const ru = language === "ru";
  const [kind, setKind] = useState<"loft" | "sweep" | "revolve">(initialKind);
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
  const [exactEdges, setExactEdges] = useState<boolean[]>([true, true, false, false]);
  const [lengths, setLengths] = useState<number[]>([20, 10, 20, 10]);
  const [fixFirst, setFixFirst] = useState(true);
  const [origin, setOrigin] = useState<Vec3>([0, 0, 0]);
  const [loftHeight, setLoftHeight] = useState(30);
  const [loftScale, setLoftScale] = useState(0.5);
  const [loftRuled, setLoftRuled] = useState(false);
  const [pathText, setPathText] = useState("0, 0, 0\n0, 0, 30\n20, 0, 50");
  const [axis, setAxis] = useState<"x" | "y" | "z">("z");
  const [angle, setAngle] = useState(360);
  const [error, setError] = useState<string | null>(null);

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
    if (points.length < 3 || points.some((point) => point.some((value) => !Number.isFinite(value)))) {
      setError(ru ? "Эскизу нужны минимум три корректные точки." : "The sketch needs at least three valid points.");
      return;
    }
    if (constraints.some((constraint) => constraint.kind === "distance" && constraint.distance_mm <= 0)) {
      setError(ru ? "Длина ребра должна быть больше нуля." : "Edge lengths must be positive.");
      return;
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
          { profile: profile(), origin_mm: origin },
          { profile: profile(loftScale), origin_mm: [origin[0], origin[1], origin[2] + loftHeight] },
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
      <strong>{ru ? "Точный B-Rep по эскизу" : "Exact B-Rep from a sketch"}</strong>
      <div className="segmented">
        {(["loft", "sweep", "revolve"] as const).map((item) => (
          <button key={item} type="button" className={kind === item ? "active" : ""} onClick={() => setKind(item)}>
            {item[0].toUpperCase() + item.slice(1)}
          </button>
        ))}
      </div>
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
            </div>
          );
        })}
        <button className="btn" type="button" onClick={addPoint}>+ {ru ? "Точка" : "Point"}</button>
      </div>

      {kind === "loft" && (
        <div className="primitive-grid two">
          <label>{ru ? "Высота, мм" : "Height, mm"}<input className="input mono" type="number" min={0.001} value={loftHeight} onChange={(event) => setLoftHeight(Number(event.target.value))} /></label>
          <label>{ru ? "Масштаб верха" : "Top scale"}<input className="input mono" type="number" min={0.01} step={0.05} value={loftScale} onChange={(event) => setLoftScale(Number(event.target.value))} /></label>
          <label className="row muted"><input type="checkbox" checked={loftRuled} onChange={(event) => setLoftRuled(event.target.checked)} />{ru ? "Линейчатая поверхность" : "Ruled surface"}</label>
        </div>
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
      {kind !== "sweep" && (
        <div className="primitive-grid three">
          {([0, 1, 2] as const).map((index) => <label key={index}>{"XYZ"[index]}<input className="input mono" type="number" value={origin[index]} onChange={(event) => setOrigin((current) => current.map((value, item) => item === index ? Number(event.target.value) : value) as Vec3)} /></label>)}
        </div>
      )}
      <div className="segmented">
        <button type="button" className={combine === "add" ? "active" : ""} onClick={() => setCombine("add")}>{ru ? "Добавить" : "Add"}</button>
        <button type="button" className={combine === "cut" ? "active" : ""} onClick={() => setCombine("cut")}>{ru ? "Вырезать" : "Cut"}</button>
      </div>
      {error && <div className="error">{error}</div>}
      <button className="btn primary" type="button" disabled={busy} onClick={() => void submit()}>
        {ru ? "Построить точное тело" : "Build exact body"}
      </button>
    </div>
  );
}
