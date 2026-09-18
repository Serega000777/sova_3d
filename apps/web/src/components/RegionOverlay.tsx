"use client";

/**
 * Outline an area on the model (T-105, F-062).
 *
 * The user drags across the model — with a mouse, a finger or a pencil — and the drawn
 * path is projected onto the surface under it. What leaves this component is geometry in
 * millimetres, never pixels: the API and the kernel work in the model's own space, and the
 * planner is held to the volume the outline sweeps (T-103).
 */
import {
  type Point2,
  type RegionSelection,
  type Surface,
  dominantAxis,
  pathToRegion,
  planeAxes,
} from "@physical-ai/contracts";
import { useCallback, useRef, useState } from "react";
import type * as THREE from "three";

export interface RegionPickResult {
  /** Where the ray hit the model, in model millimetres. */
  point: THREE.Vector3;
  /** Outward normal of the surface it hit. */
  normal: THREE.Vector3;
}

export type RegionPicker = (x: number, y: number) => RegionPickResult | null;

export interface RegionOverlayProps {
  active: boolean;
  /** Ray-casts a point in the overlay's own pixel space onto the model. */
  pick: RegionPicker;
  /** The model's size in mm — the outline reaches through the whole thickness. */
  modelSize: { x: number; y: number; z: number } | null;
  bodyId: string;
  onRegion: (region: RegionSelection | null) => void;
  /** Painting: the outline is a stroke in this colour and the hint says so. */
  paint?: string | null;
  /** Brush width in mm while painting; a sweep colours a band this wide. */
  brushMm?: number;
}

export function RegionOverlay({
  active,
  pick,
  modelSize,
  bodyId,
  onRegion,
  paint = null,
  brushMm = 4,
}: RegionOverlayProps) {
  const surface = useRef<Surface | null>(null);
  const world = useRef<Point2[]>([]);
  const [screen, setScreen] = useState<[number, number][]>([]);
  const [drawing, setDrawing] = useState(false);
  const [pointer, setPointer] = useState<string>("mouse");

  const sample = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const box = event.currentTarget.getBoundingClientRect();
      const x = event.clientX - box.left;
      const y = event.clientY - box.top;
      const hit = pick(x, y);
      if (!hit) return { x, y, hit: null };
      if (!surface.current) {
        const facing = dominantAxis(hit.normal);
        surface.current = { ...facing, offset_mm: hit.point[facing.axis] };
      }
      // The two axes that are not the surface normal, in x,y,z order — the plane the
      // outline lives in, exactly as the API expects it.
      const plane = planeAxes(surface.current.axis);
      return { x, y, hit: [hit.point[plane[0]], hit.point[plane[1]]] as Point2 };
    },
    [pick],
  );

  function start(event: React.PointerEvent<HTMLDivElement>) {
    if (!active) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setPointer(event.pointerType || "mouse");
    surface.current = null;
    world.current = [];
    const point = sample(event);
    setScreen([[point.x, point.y]]);
    if (point.hit) world.current = [point.hit];
    setDrawing(true);
    onRegion(null);
  }

  function extend(event: React.PointerEvent<HTMLDivElement>) {
    if (!active || !drawing) return;
    const point = sample(event);
    setScreen((path) => [...path, [point.x, point.y]]);
    if (point.hit) world.current = [...world.current, point.hit];
  }

  function finish(event: React.PointerEvent<HTMLDivElement>) {
    if (!active || !drawing) return;
    event.currentTarget.releasePointerCapture(event.pointerId);
    setDrawing(false);
    const face = surface.current;
    const selection =
      face && modelSize
        ? pathToRegion(world.current, {
            surface: face,
            modelSize,
            bodyId,
            brushMm: paint ? brushMm : undefined,
          })
        : null;
    if (!selection) setScreen([]); // a tap, not an outline
    onRegion(selection);
  }

  if (!active) return null;

  const outline = screen.map(([x, y]) => `${x},${y}`).join(" ");
  return (
    <div
      className="region-overlay"
      onPointerDown={start}
      onPointerMove={extend}
      onPointerUp={finish}
      onPointerCancel={finish}
    >
      <svg width="100%" height="100%">
        {screen.length > 1 && paint && (
          <polyline
            points={outline}
            fill="none"
            stroke={paint}
            strokeOpacity={0.75}
            strokeWidth={8}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}
        {screen.length > 1 && !paint && (
          <polygon
            points={outline}
            fill="rgba(91, 156, 255, 0.18)"
            stroke="var(--accent)"
            strokeWidth={2}
            strokeDasharray={drawing ? "6 4" : undefined}
          />
        )}
      </svg>
      <span className="chip region-hint">
        {drawing
          ? `drawing with ${pointer}…`
          : paint
            ? screen.length
              ? "stroke added — sweep again or keep the paint"
              : "sweep to paint a band · close the loop to fill it"
            : screen.length
              ? "region set — now say what belongs there"
              : "draw around the area you want to change"}
      </span>
    </div>
  );
}
