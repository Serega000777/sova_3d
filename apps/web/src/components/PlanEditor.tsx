"use client";

/**
 * 2D floor-plan viewer and markup (T-237, F-087). One component serves a single room and a
 * whole building: both are a `FloorPlan` in millimetres. Annotations are stored in plan
 * millimetres, so panning, zooming or loading a revised plan never moves them.
 */
import {
  ANNOTATION_COLOURS,
  type Annotation,
  type AnnotationBase,
  type AnnotationKind,
  type FloorPlan,
  type PlanFootprint,
  type Point,
  cloudPath,
  distanceBetween,
  formatLength,
  hitTest,
  moveAnnotation,
  nextPinNumber,
  planBounds,
  pointsBounds,
  roomArea,
} from "@physical-ai/contracts";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";

export type PlanTool = "select" | "hand" | AnnotationKind;

export interface PlanUnderlay {
  url: string;
  widthMm: number;
  heightMm: number;
  opacity: number;
}

interface View {
  /** Plan coordinate shown at the container's top-left, mm. */
  x: number;
  y: number;
  /** Pixels per millimetre. */
  scale: number;
}

const MIN_DRAG_MM = 20;
const PIN_PX = 13;
const SNAP_PX = 12;
const GRID_BG = "#0f1115";

function useNumberFormat() {
  return useMemo(() => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }), []);
}

/** The drawing itself, shared by the live editor and the exporter. `px` is mm per screen pixel. */
function PlanContent({
  plan,
  annotations,
  selectedId,
  draft,
  underlay,
  furniture,
  px,
  showGrid,
  theme,
}: {
  plan: FloorPlan;
  annotations: readonly Annotation[];
  selectedId: string | null;
  draft: Annotation | null;
  underlay: PlanUnderlay | null;
  furniture: readonly PlanFootprint[];
  px: number;
  showGrid: boolean;
  theme: "dark" | "light";
}) {
  const fmt = useNumberFormat();
  const bounds = planBounds(plan);
  const ink = theme === "dark" ? "#c9ced8" : "#222831";
  const wallFill = theme === "dark" ? "#8d96a6" : "#2b303a";
  const roomFill = theme === "dark" ? "rgba(91,156,255,0.07)" : "rgba(91,156,255,0.10)";
  const bg = theme === "dark" ? GRID_BG : "#ffffff";
  const gridColour = theme === "dark" ? "#20252e" : "#e6e9ef";
  const all = draft ? [...annotations, draft] : annotations;

  const gridLines: ReactNode[] = [];
  if (showGrid && bounds) {
    const step = 1000;
    const margin = 2000;
    for (let x = Math.floor((bounds.minX - margin) / step) * step; x <= bounds.maxX + margin; x += step) {
      gridLines.push(<line key={`gx${x}`} x1={x} y1={bounds.minY - margin} x2={x} y2={bounds.maxY + margin} stroke={gridColour} strokeWidth={px} />);
    }
    for (let y = Math.floor((bounds.minY - margin) / step) * step; y <= bounds.maxY + margin; y += step) {
      gridLines.push(<line key={`gy${y}`} x1={bounds.minX - margin} y1={y} x2={bounds.maxX + margin} y2={y} stroke={gridColour} strokeWidth={px} />);
    }
  }

  return (
    <>
      {underlay && (
        <image href={underlay.url} x={0} y={0} width={underlay.widthMm} height={underlay.heightMm} opacity={underlay.opacity} preserveAspectRatio="none" />
      )}
      {gridLines}
      {plan.rooms.map((room, i) => {
        const b = pointsBounds(room.outline);
        return (
          <g key={`room${i}`}>
            <polygon points={room.outline.map((p) => p.join(",")).join(" ")} fill={roomFill} />
            {b && (
              <text x={(b.minX + b.maxX) / 2} y={(b.minY + b.maxY) / 2} fill={ink} fontSize={14 * px} textAnchor="middle" opacity={0.75} style={{ pointerEvents: "none" }}>
                <tspan x={(b.minX + b.maxX) / 2}>{room.name}</tspan>
                <tspan x={(b.minX + b.maxX) / 2} dy={17 * px} fontSize={11 * px} opacity={0.7}>
                  {fmt.format(roomArea(room) / 1_000_000)} м²
                </tspan>
              </text>
            )}
          </g>
        );
      })}
      {plan.walls.map((w, i) => (
        <line key={`wall${i}`} x1={w.a[0]} y1={w.a[1]} x2={w.b[0]} y2={w.b[1]} stroke={wallFill} strokeWidth={w.thickness_mm} strokeLinecap="square" />
      ))}
      {plan.openings.map((o, i) => {
        const wall = plan.walls[o.wall];
        if (!wall) return null;
        const length = distanceBetween(wall.a, wall.b) || 1;
        const ux = (wall.b[0] - wall.a[0]) / length;
        const uy = (wall.b[1] - wall.a[1]) / length;
        const p0: Point = [wall.a[0] + ux * o.offset_mm, wall.a[1] + uy * o.offset_mm];
        const p1: Point = [p0[0] + ux * o.width_mm, p0[1] + uy * o.width_mm];
        const nx = -uy;
        const ny = ux;
        const half = wall.thickness_mm / 2;
        return (
          <g key={`open${i}`}>
            <line x1={p0[0]} y1={p0[1]} x2={p1[0]} y2={p1[1]} stroke={bg} strokeWidth={wall.thickness_mm + 4 * px} />
            {o.kind === "window" ? (
              <>
                <line x1={p0[0] + nx * half * 0.5} y1={p0[1] + ny * half * 0.5} x2={p1[0] + nx * half * 0.5} y2={p1[1] + ny * half * 0.5} stroke={ink} strokeWidth={px * 1.5} />
                <line x1={p0[0] - nx * half * 0.5} y1={p0[1] - ny * half * 0.5} x2={p1[0] - nx * half * 0.5} y2={p1[1] - ny * half * 0.5} stroke={ink} strokeWidth={px * 1.5} />
              </>
            ) : o.kind === "door" ? (
              <>
                <line x1={p0[0]} y1={p0[1]} x2={p0[0] + nx * o.width_mm} y2={p0[1] + ny * o.width_mm} stroke={ink} strokeWidth={px * 1.5} />
                <path d={`M ${p0[0] + nx * o.width_mm} ${p0[1] + ny * o.width_mm} A ${o.width_mm} ${o.width_mm} 0 0 ${nx * uy - ny * ux > 0 ? 0 : 1} ${p1[0]} ${p1[1]}`} fill="none" stroke={ink} strokeWidth={px} strokeDasharray={`${4 * px} ${3 * px}`} opacity={0.7} />
              </>
            ) : null}
          </g>
        );
      })}
      {furniture.map((item) => (
        <g
          key={`furniture-${item.nodeId}`}
          transform={`translate(${item.at[0]} ${item.at[1]}) rotate(${item.rotationDeg})`}
          style={{ pointerEvents: "none" }}
        >
          <rect
            x={-item.widthMm / 2}
            y={-item.depthMm / 2}
            width={item.widthMm}
            height={item.depthMm}
            fill={theme === "dark" ? "rgba(255,176,32,0.12)" : "rgba(255,140,0,0.12)"}
            stroke={theme === "dark" ? "#ffb020" : "#b35c00"}
            strokeWidth={px}
            strokeDasharray={`${4 * px} ${3 * px}`}
          />
          <text
            x={0}
            y={0}
            fontSize={11 * px}
            textAnchor="middle"
            dominantBaseline="middle"
            fill={theme === "dark" ? "#ffb020" : "#b35c00"}
            transform={`rotate(${-item.rotationDeg})`}
          >
            {item.label}
          </text>
        </g>
      ))}
      {all.map((a) => (
        <AnnotationShape key={a.id} a={a} px={px} selected={a.id === selectedId} />
      ))}
    </>
  );
}

function AnnotationShape({ a, px, selected }: { a: Annotation; px: number; selected: boolean }) {
  const width = 2.2 * px;
  const common = {
    stroke: a.colour,
    strokeWidth: width,
    fill: "none",
    opacity: a.status === "resolved" ? 0.4 : 1,
    style: { pointerEvents: "none" } as const,
  };
  let body: ReactNode = null;
  switch (a.kind) {
    case "pin":
      body = (
        <g opacity={a.status === "resolved" ? 0.4 : 1}>
          <circle cx={a.at[0]} cy={a.at[1]} r={PIN_PX * px} fill={a.colour} stroke="#0b0d12" strokeWidth={1.5 * px} />
          <text x={a.at[0]} y={a.at[1] + 4.5 * px} fontSize={13 * px} fontWeight={700} textAnchor="middle" fill="#0b0d12">
            {a.status === "resolved" ? "✓" : a.number}
          </text>
        </g>
      );
      break;
    case "rect":
      body = <rect {...common} x={Math.min(a.from[0], a.to[0])} y={Math.min(a.from[1], a.to[1])} width={Math.abs(a.to[0] - a.from[0])} height={Math.abs(a.to[1] - a.from[1])} />;
      break;
    case "cloud":
      body = <path {...common} d={cloudPath(a.from, a.to, 26 * px)} />;
      break;
    case "circle":
      body = <circle {...common} cx={a.centre[0]} cy={a.centre[1]} r={a.radius_mm} />;
      break;
    case "freehand":
      body = <polyline {...common} strokeLinejoin="round" strokeLinecap="round" points={a.points.map((p) => p.join(",")).join(" ")} />;
      break;
    case "arrow": {
      const angle = Math.atan2(a.to[1] - a.from[1], a.to[0] - a.from[0]);
      const head = 12 * px;
      const left: Point = [a.to[0] - head * Math.cos(angle - 0.45), a.to[1] - head * Math.sin(angle - 0.45)];
      const right: Point = [a.to[0] - head * Math.cos(angle + 0.45), a.to[1] - head * Math.sin(angle + 0.45)];
      body = (
        <g {...common}>
          <line x1={a.from[0]} y1={a.from[1]} x2={a.to[0]} y2={a.to[1]} />
          <polyline points={`${left.join(",")} ${a.to.join(",")} ${right.join(",")}`} strokeLinejoin="round" />
        </g>
      );
      break;
    }
    case "dimension": {
      const length = distanceBetween(a.from, a.to);
      const angle = (Math.atan2(a.to[1] - a.from[1], a.to[0] - a.from[0]) * 180) / Math.PI;
      const mid: Point = [(a.from[0] + a.to[0]) / 2, (a.from[1] + a.to[1]) / 2];
      const flip = angle > 90 || angle < -90 ? 180 : 0; // keep the figure upright
      const tick = 7 * px;
      const nx = -(a.to[1] - a.from[1]) / (length || 1);
      const ny = (a.to[0] - a.from[0]) / (length || 1);
      body = (
        <g {...common}>
          <line x1={a.from[0]} y1={a.from[1]} x2={a.to[0]} y2={a.to[1]} />
          {[a.from, a.to].map((p, i) => (
            <line key={i} x1={p[0] - nx * tick} y1={p[1] - ny * tick} x2={p[0] + nx * tick} y2={p[1] + ny * tick} />
          ))}
          <text x={mid[0]} y={mid[1] - 6 * px} fontSize={13 * px} fill={a.colour} stroke="#0b0d12" strokeWidth={3 * px} paintOrder="stroke" textAnchor="middle" transform={`rotate(${angle + flip} ${mid[0]} ${mid[1]})`}>
            {formatLength(length)}
          </text>
        </g>
      );
      break;
    }
    case "text":
      body = (
        <text x={a.at[0]} y={a.at[1] + a.size_mm} fontSize={a.size_mm} fill={a.colour} stroke="#0b0d12" strokeWidth={3 * px} paintOrder="stroke" opacity={a.status === "resolved" ? 0.4 : 1} style={{ pointerEvents: "none" }}>
          {a.text}
        </text>
      );
      break;
  }
  const b = selected ? selectionBox(a, px) : null;
  return (
    <>
      {body}
      {b && <rect x={b.x} y={b.y} width={b.w} height={b.h} fill="none" stroke="#5b9cff" strokeWidth={px} strokeDasharray={`${5 * px} ${4 * px}`} style={{ pointerEvents: "none" }} />}
    </>
  );
}

function selectionBox(a: Annotation, px: number) {
  const pad = 8 * px;
  let minX: number;
  let minY: number;
  let maxX: number;
  let maxY: number;
  switch (a.kind) {
    case "pin":
      minX = a.at[0] - PIN_PX * px;
      maxX = a.at[0] + PIN_PX * px;
      minY = a.at[1] - PIN_PX * px;
      maxY = a.at[1] + PIN_PX * px;
      break;
    case "circle":
      minX = a.centre[0] - a.radius_mm;
      maxX = a.centre[0] + a.radius_mm;
      minY = a.centre[1] - a.radius_mm;
      maxY = a.centre[1] + a.radius_mm;
      break;
    case "text":
      minX = a.at[0];
      minY = a.at[1];
      maxX = a.at[0] + a.text.length * a.size_mm * 0.6;
      maxY = a.at[1] + a.size_mm * 1.2;
      break;
    case "freehand": {
      const b = pointsBounds(a.points) ?? { minX: 0, minY: 0, maxX: 0, maxY: 0 };
      ({ minX, minY, maxX, maxY } = b);
      break;
    }
    default:
      minX = Math.min(a.from[0], a.to[0]);
      maxX = Math.max(a.from[0], a.to[0]);
      minY = Math.min(a.from[1], a.to[1]);
      maxY = Math.max(a.from[1], a.to[1]);
  }
  return { x: minX - pad, y: minY - pad, w: maxX - minX + pad * 2, h: maxY - minY + pad * 2 };
}

function snapTo(point: Point, plan: FloorPlan, tolerance_mm: number): Point {
  let best: Point | null = null;
  let bestDistance = tolerance_mm;
  const candidates: Point[] = [...plan.walls.flatMap((w) => [w.a, w.b]), ...plan.rooms.flatMap((r) => r.outline)];
  for (const c of candidates) {
    const d = distanceBetween(point, c);
    if (d <= bestDistance) {
      best = c;
      bestDistance = d;
    }
  }
  return best ?? point;
}

let idCounter = 0;
function newId(): string {
  idCounter += 1;
  return `a${Date.now().toString(36)}${idCounter}`;
}

export interface PlanEditorHandle {
  fit(): void;
}

export function PlanEditor({
  plan,
  annotations,
  onChange,
  selectedId,
  onSelect,
  tool,
  colour,
  author,
  underlay,
  furniture,
  showGrid,
  fitRevision,
  language,
}: {
  plan: FloorPlan;
  annotations: readonly Annotation[];
  onChange: (next: Annotation[]) => void;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  tool: PlanTool;
  colour: string;
  author: string;
  underlay: PlanUnderlay | null;
  /** Real-scale furniture footprints, projected from the version's scene graph. Read-only. */
  furniture?: readonly PlanFootprint[];
  showGrid: boolean;
  /** Bump to re-frame the plan. */
  fitRevision: number;
  language: "en" | "ru";
}) {
  const ru = language === "ru";
  const hostRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 800, height: 600 });
  const [view, setView] = useState<View>({ x: -500, y: -500, scale: 0.08 });
  const [draft, setDraft] = useState<Annotation | null>(null);
  const [textDraft, setTextDraft] = useState<{ at: Point; value: string } | null>(null);
  const gesture = useRef<
    | { kind: "pan"; startX: number; startY: number; view: View }
    | { kind: "draw"; start: Point }
    | { kind: "move"; id: string; last: Point; moved: boolean; original: Annotation }
    | null
  >(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ distance: number; view: View; centre: { x: number; y: number } } | null>(null);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setSize({ width: el.clientWidth, height: el.clientHeight }));
    observer.observe(el);
    setSize({ width: el.clientWidth, height: el.clientHeight });
    return () => observer.disconnect();
  }, []);

  const fit = useCallback(() => {
    const b = planBounds(plan);
    if (!b) return;
    const w = Math.max(b.maxX - b.minX, 1000);
    const h = Math.max(b.maxY - b.minY, 1000);
    const scale = Math.min((size.width - 80) / w, (size.height - 80) / h);
    setView({ scale, x: b.minX - (size.width / scale - (b.maxX - b.minX)) / 2, y: b.minY - (size.height / scale - (b.maxY - b.minY)) / 2 });
  }, [plan, size.height, size.width]);
  // Re-frame when the plan or the requested revision changes, not on every resize.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(fit, [plan.id, fitRevision]);

  const toPlan = useCallback(
    (clientX: number, clientY: number): Point => {
      const rect = hostRef.current?.getBoundingClientRect();
      const x = clientX - (rect?.left ?? 0);
      const y = clientY - (rect?.top ?? 0);
      return [view.x + x / view.scale, view.y + y / view.scale];
    },
    [view],
  );
  const px = 1 / view.scale;

  const zoomAt = useCallback((clientX: number, clientY: number, factor: number) => {
    const rect = hostRef.current?.getBoundingClientRect();
    const sx = clientX - (rect?.left ?? 0);
    const sy = clientY - (rect?.top ?? 0);
    setView((v) => {
      const scale = Math.min(Math.max(v.scale * factor, 0.005), 4);
      const mx = v.x + sx / v.scale;
      const my = v.y + sy / v.scale;
      return { scale, x: mx - sx / scale, y: my - sy / scale };
    });
  }, []);

  // Wheel needs a non-passive listener to stop the page from scrolling under the plan.
  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.0015));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  const makeBase = (): AnnotationBase => ({
    id: newId(),
    author,
    created_at: new Date().toISOString(),
    status: "open",
    note: "",
    colour,
  });

  const dragShape = (start: Point, end: Point, kind: AnnotationKind): Annotation | null => {
    const base = makeBase();
    switch (kind) {
      case "rect":
      case "cloud":
      case "arrow":
      case "dimension":
        return { ...base, kind, from: start, to: end };
      case "circle":
        return { ...base, kind: "circle", centre: start, radius_mm: distanceBetween(start, end) };
      default:
        return null;
    }
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (textDraft) {
      // a click elsewhere finishes the label being typed instead of starting another
      commitText();
      return;
    }
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      // a second finger turns whatever was happening into a pinch
      gesture.current = null;
      setDraft(null);
      const [a, b] = [...pointers.current.values()] as [{ x: number; y: number }, { x: number; y: number }];
      pinch.current = { distance: Math.hypot(b.x - a.x, b.y - a.y), view, centre: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } };
      return;
    }
    const spacePan = e.button === 1 || e.button === 2 || tool === "hand";
    if (spacePan) {
      gesture.current = { kind: "pan", startX: e.clientX, startY: e.clientY, view };
      return;
    }
    const at = toPlan(e.clientX, e.clientY);
    const tolerance = 10 * px;
    if (tool === "select") {
      const hit = hitTest(annotations, at, tolerance);
      onSelect(hit ? hit.id : null);
      gesture.current = hit
        ? { kind: "move", id: hit.id, last: at, moved: false, original: hit }
        : { kind: "pan", startX: e.clientX, startY: e.clientY, view };
      return;
    }
    const point = snapTo(at, plan, SNAP_PX * px);
    if (tool === "pin") {
      const next: Annotation = { ...makeBase(), kind: "pin", at: point, number: nextPinNumber(annotations) };
      onChange([...annotations, next]);
      onSelect(next.id);
      return;
    }
    if (tool === "text") {
      setTextDraft({ at: point, value: "" });
      return;
    }
    gesture.current = { kind: "draw", start: point };
    if (tool === "freehand") setDraft({ ...makeBase(), kind: "freehand", points: [point, point] });
    else setDraft(dragShape(point, point, tool));
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (pointers.current.has(e.pointerId)) pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch.current && pointers.current.size >= 2) {
      const [a, b] = [...pointers.current.values()] as [{ x: number; y: number }, { x: number; y: number }];
      const distance = Math.hypot(b.x - a.x, b.y - a.y);
      const start = pinch.current;
      const scale = Math.min(Math.max(start.view.scale * (distance / start.distance), 0.005), 4);
      const rect = hostRef.current?.getBoundingClientRect();
      const cx = start.centre.x - (rect?.left ?? 0);
      const cy = start.centre.y - (rect?.top ?? 0);
      const mx = start.view.x + cx / start.view.scale;
      const my = start.view.y + cy / start.view.scale;
      const nowX = (a.x + b.x) / 2 - (rect?.left ?? 0);
      const nowY = (a.y + b.y) / 2 - (rect?.top ?? 0);
      setView({ scale, x: mx - nowX / scale, y: my - nowY / scale });
      return;
    }
    const g = gesture.current;
    if (!g) return;
    if (g.kind === "pan") {
      setView({ ...g.view, x: g.view.x - (e.clientX - g.startX) / g.view.scale, y: g.view.y - (e.clientY - g.startY) / g.view.scale });
    } else if (g.kind === "draw") {
      const point = snapTo(toPlan(e.clientX, e.clientY), plan, SNAP_PX * px);
      if (tool === "freehand") {
        setDraft((d) => (d && d.kind === "freehand" ? { ...d, points: [...d.points, point] } : d));
      } else {
        setDraft(dragShape(g.start, point, tool as AnnotationKind));
      }
    } else if (g.kind === "move") {
      const at = toPlan(e.clientX, e.clientY);
      const dx = at[0] - g.last[0];
      const dy = at[1] - g.last[1];
      if (!g.moved && Math.hypot(dx, dy) < 3 * px) return;
      g.moved = true;
      g.last = at;
      onChange(annotations.map((a) => (a.id === g.id ? moveAnnotation(a, dx, dy) : a)));
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
    const g = gesture.current;
    gesture.current = null;
    if (g?.kind === "draw" && draft) {
      const b = draft.kind === "freehand" ? pointsBounds(draft.points) : null;
      const big =
        draft.kind === "freehand"
          ? b !== null && Math.hypot(b.maxX - b.minX, b.maxY - b.minY) > MIN_DRAG_MM
          : draft.kind === "circle"
            ? draft.radius_mm > MIN_DRAG_MM
            : "from" in draft && distanceBetween(draft.from, draft.to) > MIN_DRAG_MM;
      if (big) {
        onChange([...annotations, draft]);
        onSelect(draft.id);
      }
      setDraft(null);
    }
  };

  function commitText() {
    if (textDraft && textDraft.value.trim()) {
      const next: Annotation = { ...makeBase(), kind: "text", at: textDraft.at, text: textDraft.value.trim(), size_mm: 14 * px };
      onChange([...annotations, next]);
      onSelect(next.id);
    }
    setTextDraft(null);
  }

  const cursor = tool === "hand" ? "grab" : tool === "select" ? "default" : "crosshair";
  return (
    <div
      ref={hostRef}
      className="plan-canvas"
      style={{ cursor }}
      onPointerDown={onPointerDown}
      // the label input is focused on pointerdown; letting mousedown move focus would blur it at once
      onMouseDown={(e) => tool === "text" && !(e.target instanceof HTMLInputElement) && e.preventDefault()}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onContextMenu={(e) => e.preventDefault()}
    >
      <svg width={size.width} height={size.height} role="img" aria-label={ru ? "План" : "Plan"}>
        <g transform={`scale(${view.scale}) translate(${-view.x} ${-view.y})`}>
          <PlanContent plan={plan} annotations={annotations} selectedId={selectedId} draft={draft} underlay={underlay} furniture={furniture ?? []} px={px} showGrid={showGrid} theme="dark" />
        </g>
        <ScaleBar scale={view.scale} height={size.height} />
      </svg>
      {textDraft && (
        <input
          className="plan-text-input"
          autoFocus
          value={textDraft.value}
          style={{ left: (textDraft.at[0] - view.x) * view.scale, top: (textDraft.at[1] - view.y) * view.scale }}
          placeholder={ru ? "Текст…" : "Text…"}
          onPointerDown={(e) => e.stopPropagation()}
          onChange={(e) => setTextDraft({ ...textDraft, value: e.target.value })}
          onBlur={commitText}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitText();
            if (e.key === "Escape") setTextDraft(null);
          }}
        />
      )}
      <div className="plan-zoom">
        <button type="button" aria-label="+" onClick={() => zoomAt(size.width / 2 + (hostRef.current?.getBoundingClientRect().left ?? 0), size.height / 2 + (hostRef.current?.getBoundingClientRect().top ?? 0), 1.3)}>+</button>
        <button type="button" aria-label="−" onClick={() => zoomAt(size.width / 2 + (hostRef.current?.getBoundingClientRect().left ?? 0), size.height / 2 + (hostRef.current?.getBoundingClientRect().top ?? 0), 1 / 1.3)}>−</button>
        <button type="button" aria-label={ru ? "Вписать" : "Fit"} onClick={fit}>⤢</button>
      </div>
    </div>
  );
}

function ScaleBar({ scale, height }: { scale: number; height: number }) {
  // the longest round length that fits in ~140 px
  const steps = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000];
  const mm = [...steps].reverse().find((s) => s * scale <= 140) ?? steps[0]!;
  const width = mm * scale;
  return (
    <g transform={`translate(16 ${height - 22})`} style={{ pointerEvents: "none" }}>
      <line x1={0} y1={0} x2={width} y2={0} stroke="#c9ced8" strokeWidth={2} />
      <line x1={0} y1={-5} x2={0} y2={5} stroke="#c9ced8" strokeWidth={2} />
      <line x1={width} y1={-5} x2={width} y2={5} stroke="#c9ced8" strokeWidth={2} />
      <text x={width + 8} y={4} fontSize={12} fill="#c9ced8">
        {formatLength(mm)}
      </text>
    </g>
  );
}

/** The marked-up plan as a standalone SVG document (light theme, fixed pixel scale). */
export function exportPlanSvg(plan: FloorPlan, annotations: readonly Annotation[], underlay: PlanUnderlay | null, furniture: readonly PlanFootprint[] = []): { svg: string; width: number; height: number } {
  const b = planBounds(plan) ?? { minX: 0, minY: 0, maxX: 1000, maxY: 1000 };
  const margin = 600;
  const pxPerMm = 0.12; // 1 px = ~8.3 mm; a 10 m house is ~1200 px wide
  const widthMm = b.maxX - b.minX + margin * 2;
  const heightMm = b.maxY - b.minY + margin * 2;
  const width = Math.round(widthMm * pxPerMm);
  const height = Math.round(heightMm * pxPerMm);
  const svg = renderToStaticMarkup(
    <svg xmlns="http://www.w3.org/2000/svg" width={width} height={height} viewBox={`${b.minX - margin} ${b.minY - margin} ${widthMm} ${heightMm}`} fontFamily="system-ui, sans-serif">
      <rect x={b.minX - margin} y={b.minY - margin} width={widthMm} height={heightMm} fill="#ffffff" />
      <PlanContent plan={plan} annotations={annotations} selectedId={null} draft={null} underlay={underlay} furniture={furniture} px={1 / pxPerMm} showGrid theme="light" />
    </svg>,
  );
  return { svg, width, height };
}
