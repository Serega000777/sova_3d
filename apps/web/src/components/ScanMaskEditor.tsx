"use client";

import { useMemo, useRef, useState } from "react";

export interface MaskPoint {
  x: number;
  y: number;
}

export interface ManualMaskStroke {
  mode: "add" | "remove";
  radius: number;
  points: MaskPoint[];
}

export interface FrameMaskCorrection {
  sequence_no: number;
  strokes: ManualMaskStroke[];
}

interface MaskFrameSource {
  sequenceNo: number;
  url: string;
}

function pathFor(points: MaskPoint[]): string {
  return points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x * 100} ${point.y * 100}`)
    .join(" ");
}

export function ScanMaskEditor({
  frames,
  value,
  onChange,
  ru,
}: {
  frames: MaskFrameSource[];
  value: FrameMaskCorrection[];
  onChange: (value: FrameMaskCorrection[]) => void;
  ru: boolean;
}) {
  const [selected, setSelected] = useState(frames[0]?.sequenceNo ?? 0);
  const [mode, setMode] = useState<"add" | "remove">("add");
  const [radius, setRadius] = useState(0.04);
  const [draft, setDraft] = useState<ManualMaskStroke | null>(null);
  const pointerId = useRef<number | null>(null);
  const frame = frames.find((item) => item.sequenceNo === selected) ?? frames[0];
  const correction = value.find((item) => item.sequence_no === frame?.sequenceNo);
  const strokes = correction?.strokes ?? [];
  const visibleStrokes = useMemo(() => (draft ? [...strokes, draft] : strokes), [draft, strokes]);

  if (!frame) return null;

  function pointFromEvent(event: React.PointerEvent<SVGSVGElement>): MaskPoint {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    };
  }

  function replaceCurrent(nextStrokes: ManualMaskStroke[]) {
    const other = value.filter((item) => item.sequence_no !== frame.sequenceNo);
    onChange(
      nextStrokes.length
        ? [...other, { sequence_no: frame.sequenceNo, strokes: nextStrokes }].sort(
            (a, b) => a.sequence_no - b.sequence_no,
          )
        : other,
    );
  }

  function finishStroke() {
    if (draft?.points.length) replaceCurrent([...strokes, draft]);
    setDraft(null);
    pointerId.current = null;
  }

  return (
    <section className="card stack" aria-label={ru ? "Ручная коррекция маски" : "Manual mask correction"}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="stack" style={{ gap: 2 }}>
          <strong>{ru ? "Ручная коррекция маски" : "Manual mask correction"}</strong>
          <span className="muted" style={{ fontSize: 12 }}>
            {ru
              ? "Кисть меняет автоматическую U²-Net маску перед реконструкцией. Оранжевое добавляет объект, тёмное удаляет фон."
              : "The brush adjusts the automatic U²-Net mask before reconstruction. Orange keeps the object; dark removes background."}
          </span>
        </div>
        <span className="chip">{ru ? "Кадр" : "Frame"} {frame.sequenceNo + 1}</span>
      </div>

      <div className="row" style={{ alignItems: "stretch", flexWrap: "wrap" }}>
        <figure className="stack" style={{ flex: "1 1 260px", margin: 0, gap: 4 }}>
          <figcaption className="muted">{ru ? "До · исходный кадр" : "Before · source frame"}</figcaption>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={frame.url} alt="" style={{ width: "100%", borderRadius: 10, display: "block" }} />
        </figure>
        <figure className="stack" style={{ flex: "1 1 260px", margin: 0, gap: 4 }}>
          <figcaption className="muted">{ru ? "После · правки поверх авто-маски" : "After · edits over auto mask"}</figcaption>
          <div style={{ position: "relative", lineHeight: 0 }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={frame.url} alt="" style={{ width: "100%", borderRadius: 10, display: "block" }} />
            <svg
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              style={{ position: "absolute", inset: 0, width: "100%", height: "100%", touchAction: "none" }}
              aria-label={ru ? "Холст кисти маски" : "Mask brush canvas"}
              onPointerDown={(event) => {
                if (pointerId.current !== null || strokes.length >= 64) return;
                pointerId.current = event.pointerId;
                event.currentTarget.setPointerCapture(event.pointerId);
                setDraft({ mode, radius, points: [pointFromEvent(event)] });
              }}
              onPointerMove={(event) => {
                if (pointerId.current !== event.pointerId) return;
                const point = pointFromEvent(event);
                setDraft((current) => {
                  if (!current || current.points.length >= 512) return current;
                  const last = current.points.at(-1);
                  if (last && Math.hypot(point.x - last.x, point.y - last.y) < 0.003) return current;
                  return { ...current, points: [...current.points, point] };
                });
              }}
              onPointerUp={finishStroke}
              onPointerCancel={() => {
                setDraft(null);
                pointerId.current = null;
              }}
            >
              {visibleStrokes.map((stroke, index) => (
                <g key={`${index}-${stroke.mode}`}>
                  <path
                    d={pathFor(stroke.points)}
                    fill="none"
                    stroke={stroke.mode === "add" ? "rgba(255,109,0,0.72)" : "rgba(12,15,20,0.78)"}
                    strokeWidth={stroke.radius * 200}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  {stroke.points[0] && (
                    <circle
                      cx={stroke.points[0].x * 100}
                      cy={stroke.points[0].y * 100}
                      r={stroke.radius * 100}
                      fill={stroke.mode === "add" ? "rgba(255,109,0,0.72)" : "rgba(12,15,20,0.78)"}
                    />
                  )}
                </g>
              ))}
            </svg>
          </div>
        </figure>
      </div>

      <div className="row">
        <button className={`btn ${mode === "add" ? "primary" : ""}`} type="button" onClick={() => setMode("add")}>
          {ru ? "Добавить в объект" : "Keep object"}
        </button>
        <button className={`btn ${mode === "remove" ? "primary" : ""}`} type="button" onClick={() => setMode("remove")}>
          {ru ? "Удалить фон" : "Remove background"}
        </button>
        <label className="row" style={{ gap: 6 }}>
          <span className="muted">{ru ? "Размер" : "Size"}</span>
          <input
            type="range"
            min={0.01}
            max={0.15}
            step={0.01}
            value={radius}
            onChange={(event) => setRadius(Number(event.target.value))}
          />
          <span className="mono">{Math.round(radius * 100)}%</span>
        </label>
        <button className="btn" type="button" disabled={!strokes.length} onClick={() => replaceCurrent(strokes.slice(0, -1))}>
          {ru ? "Отменить штрих" : "Undo stroke"}
        </button>
        <button className="btn" type="button" disabled={!strokes.length} onClick={() => replaceCurrent([])}>
          {ru ? "Очистить кадр" : "Clear frame"}
        </button>
        <button
          className="btn"
          type="button"
          disabled={!strokes.length || frames.length < 2}
          onClick={() =>
            onChange(frames.map((item) => ({ sequence_no: item.sequenceNo, strokes: structuredClone(strokes) })))
          }
        >
          {ru ? `Применить эти штрихи ко всем (${frames.length})` : `Apply these strokes to all (${frames.length})`}
        </button>
      </div>

      <div className="row" style={{ flexWrap: "nowrap", overflowX: "auto" }}>
        {frames.map((item) => {
          const count = value.find((entry) => entry.sequence_no === item.sequenceNo)?.strokes.length ?? 0;
          return (
            <button
              className={`btn ${item.sequenceNo === frame.sequenceNo ? "primary" : ""}`}
              type="button"
              key={item.sequenceNo}
              onClick={() => setSelected(item.sequenceNo)}
            >
              {ru ? "Кадр" : "Frame"} {item.sequenceNo + 1}{count ? ` · ${count}` : ""}
            </button>
          );
        })}
      </div>
    </section>
  );
}
