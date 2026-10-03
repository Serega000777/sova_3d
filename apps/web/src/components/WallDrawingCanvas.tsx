"use client";

/**
 * Freeform wall drawing for the "from scratch" house-design path (T-238): a plain SVG canvas
 * where clicks place `PlanWall` segments in plan millimetres — the exact model `PlanEditor`
 * already renders, just produced by hand instead of a scan or a demo generator.
 */
import { type PlanWall, type Point, distanceBetween, isClosedWallLoop, openWallEndpoints } from "@physical-ai/contracts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { hitWallIndex, rectangleWalls, snapPoint } from "@/lib/wall-drawing";

export type WallDrawTool = "wall" | "room" | "erase";

interface View {
  /** Plan coordinate shown at the container's top-left, mm. */
  x: number;
  y: number;
  /** Pixels per millimetre. */
  scale: number;
}

const MAJOR_GRID_MM = 1000;
const SNAP_PX = 14;
const MIN_WALL_MM = 200;
const OPEN_MARK_PX = 9;

export function WallDrawingCanvas({
  walls,
  onChange,
  wallThicknessMm = 120,
  language,
}: {
  walls: PlanWall[];
  onChange: (next: PlanWall[]) => void;
  wallThicknessMm?: number;
  language: "en" | "ru";
}) {
  const ru = language === "ru";
  const hostRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 800, height: 520 });
  const [view, setView] = useState<View>({ x: -1000, y: -1000, scale: 0.08 });
  const [tool, setTool] = useState<WallDrawTool>("wall");
  const [pending, setPending] = useState<Point | null>(null);
  const [roomStart, setRoomStart] = useState<Point | null>(null);
  const [hover, setHover] = useState<Point | null>(null);
  const firstFit = useRef(false);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setSize({ width: el.clientWidth, height: el.clientHeight }));
    observer.observe(el);
    setSize({ width: el.clientWidth, height: el.clientHeight });
    return () => observer.disconnect();
  }, []);

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
  const tolerance = SNAP_PX * px;

  const fit = useCallback(() => {
    const points = walls.flatMap((w) => [w.a, w.b]);
    const bounds = points.length
      ? {
          minX: Math.min(...points.map((p) => p[0])),
          minY: Math.min(...points.map((p) => p[1])),
          maxX: Math.max(...points.map((p) => p[0])),
          maxY: Math.max(...points.map((p) => p[1])),
        }
      : { minX: 0, minY: 0, maxX: 10_000, maxY: 8_000 };
    const margin = 1500;
    const w = Math.max(bounds.maxX - bounds.minX + margin * 2, 2000);
    const h = Math.max(bounds.maxY - bounds.minY + margin * 2, 2000);
    const scale = Math.min((size.width || 800) / w, (size.height || 520) / h);
    setView({
      scale,
      x: bounds.minX - margin - ((size.width || 800) / scale - w) / 2,
      y: bounds.minY - margin - ((size.height || 520) / scale - h) / 2,
    });
  }, [walls, size.width, size.height]);

  // Fit once the host has a real size; afterwards the user's own pan/zoom is left alone.
  useEffect(() => {
    if (firstFit.current || size.width === 0) return;
    firstFit.current = true;
    fit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [size.width, size.height]);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      setView((v) => {
        const scale = Math.min(Math.max(v.scale * Math.exp(-e.deltaY * 0.0015), 0.01), 2);
        const mx = v.x + sx / v.scale;
        const my = v.y + sy / v.scale;
        return { scale, x: mx - sx / scale, y: my - sy / scale };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const openEnds = useMemo(() => openWallEndpoints(walls), [walls]);
  const closed = useMemo(() => isClosedWallLoop(walls), [walls]);

  function cancelDraft() {
    setPending(null);
    setRoomStart(null);
  }

  function selectTool(next: WallDrawTool) {
    setTool(next);
    cancelDraft();
  }

  function onPointerDown(e: React.PointerEvent) {
    if (e.button === 2) return;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    const raw = toPlan(e.clientX, e.clientY);

    if (tool === "erase") {
      const hit = hitWallIndex(raw, walls, tolerance);
      if (hit !== null) onChange(walls.filter((_, i) => i !== hit));
      return;
    }

    const snapped = snapPoint(raw, walls, tolerance);
    if (tool === "wall") {
      if (!pending) {
        setPending(snapped);
      } else {
        if (distanceBetween(pending, snapped) >= MIN_WALL_MM) {
          onChange([...walls, { a: pending, b: snapped, thickness_mm: wallThicknessMm }]);
        }
        setPending(null);
      }
      return;
    }

    if (tool === "room") {
      setRoomStart(snapped);
    }
  }

  function onPointerMove(e: React.PointerEvent) {
    const raw = toPlan(e.clientX, e.clientY);
    setHover(snapPoint(raw, walls, tolerance));
  }

  function onPointerUp(e: React.PointerEvent) {
    if (tool !== "room" || !roomStart) return;
    const raw = toPlan(e.clientX, e.clientY);
    const end = snapPoint(raw, walls, tolerance);
    if (Math.abs(end[0] - roomStart[0]) >= MIN_WALL_MM && Math.abs(end[1] - roomStart[1]) >= MIN_WALL_MM) {
      onChange([...walls, ...rectangleWalls(roomStart, end, wallThicknessMm)]);
    }
    setRoomStart(null);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") cancelDraft();
  }

  function undo() {
    onChange(walls.slice(0, -1));
    cancelDraft();
  }

  const cursor = tool === "erase" ? "not-allowed" : "crosshair";
  const gridLines = buildGridLines(view, size, px);

  return (
    <div className="wall-canvas">
      <div className="wall-canvas-toolbar" role="toolbar" aria-label={ru ? "Инструменты рисования стен" : "Wall drawing tools"}>
        <button type="button" className={`btn ${tool === "wall" ? "active" : ""}`} onClick={() => selectTool("wall")}>
          {ru ? "✎ Стена" : "✎ Wall"}
        </button>
        <button type="button" className={`btn ${tool === "room" ? "active" : ""}`} onClick={() => selectTool("room")}>
          {ru ? "▭ Комната" : "▭ Room"}
        </button>
        <button type="button" className={`btn ${tool === "erase" ? "active" : ""}`} onClick={() => selectTool("erase")}>
          {ru ? "⌫ Удалить стену" : "⌫ Erase wall"}
        </button>
        <span className="plan-sep" />
        <button type="button" className="btn" disabled={walls.length === 0} onClick={undo}>
          {ru ? "↶ Отменить" : "↶ Undo"}
        </button>
        <button type="button" className="btn" onClick={fit}>
          {ru ? "⤢ Вписать" : "⤢ Fit"}
        </button>
        <span className={`wall-canvas-status ${closed ? "ok" : ""}`}>
          {walls.length === 0
            ? ru
              ? "Нарисуйте первую стену"
              : "Draw the first wall"
            : closed
              ? ru
                ? "Контур замкнут ✓"
                : "Perimeter closed ✓"
              : ru
                ? `Свободных концов: ${openEnds.length}`
                : `Open ends: ${openEnds.length}`}
        </span>
      </div>
      <div
        ref={hostRef}
        className="wall-canvas-host"
        style={{ cursor }}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onKeyDown={onKeyDown}
        onContextMenu={(e) => e.preventDefault()}
      >
        <svg width={size.width} height={size.height} role="img" aria-label={ru ? "Холст стен" : "Wall canvas"}>
          <g transform={`scale(${view.scale}) translate(${-view.x} ${-view.y})`}>
            {gridLines}
            {walls.map((w, i) => (
              <line
                key={`w${i}`}
                x1={w.a[0]}
                y1={w.a[1]}
                x2={w.b[0]}
                y2={w.b[1]}
                stroke={tool === "erase" ? "#ff8a6b" : "#8d96a6"}
                strokeWidth={w.thickness_mm}
                strokeLinecap="square"
              />
            ))}
            {openEnds.map((p, i) => (
              <circle key={`open${i}`} cx={p[0]} cy={p[1]} r={OPEN_MARK_PX * px} fill="none" stroke="#ff4d4f" strokeWidth={2.5 * px} />
            ))}
            {tool === "wall" && pending && hover && (
              <line x1={pending[0]} y1={pending[1]} x2={hover[0]} y2={hover[1]} stroke="#5b9cff" strokeWidth={wallThicknessMm} strokeLinecap="square" opacity={0.55} />
            )}
            {tool === "wall" && pending && (
              <circle cx={pending[0]} cy={pending[1]} r={6 * px} fill="#5b9cff" />
            )}
            {tool === "room" && roomStart && hover && (
              <rect
                x={Math.min(roomStart[0], hover[0])}
                y={Math.min(roomStart[1], hover[1])}
                width={Math.abs(hover[0] - roomStart[0])}
                height={Math.abs(hover[1] - roomStart[1])}
                fill="rgba(91,156,255,0.12)"
                stroke="#5b9cff"
                strokeWidth={2 * px}
                strokeDasharray={`${6 * px} ${4 * px}`}
              />
            )}
          </g>
        </svg>
      </div>
    </div>
  );
}

function buildGridLines(view: View, size: { width: number; height: number }, px: number) {
  const minX = view.x;
  const minY = view.y;
  const maxX = view.x + size.width * px;
  const maxY = view.y + size.height * px;
  const lines = [];
  for (let x = Math.floor(minX / MAJOR_GRID_MM) * MAJOR_GRID_MM; x <= maxX; x += MAJOR_GRID_MM) {
    lines.push(<line key={`gx${x}`} x1={x} y1={minY} x2={x} y2={maxY} stroke="#20252e" strokeWidth={px} />);
  }
  for (let y = Math.floor(minY / MAJOR_GRID_MM) * MAJOR_GRID_MM; y <= maxY; y += MAJOR_GRID_MM) {
    lines.push(<line key={`gy${y}`} x1={minX} y1={y} x2={maxX} y2={y} stroke="#20252e" strokeWidth={px} />);
  }
  return lines;
}
