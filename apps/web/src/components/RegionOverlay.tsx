"use client";

/**
 * Outline an area on the model (T-105, F-062).
 *
 * The user drags across the model — with a mouse, a finger or a pencil — and the drawn
 * path is projected onto the surface under it. What leaves this component is geometry in
 * millimetres, never pixels: the API and the kernel work in the model's own space, and the
 * planner is held to the volume the outline sweeps (T-103).
 */
import type { LassoRegion, RegionSelection } from "@physical-ai/contracts";
import { useCallback, useRef, useState } from "react";
import * as THREE from "three";

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
}

const AXES = ["x", "y", "z"] as const;
type Axis = (typeof AXES)[number];

/** The axis the surface faces, from its normal: the component that dominates. */
function dominantAxis(normal: THREE.Vector3): { axis: Axis; sign: "+" | "-" } {
  const components: [Axis, number][] = [
    ["x", normal.x],
    ["y", normal.y],
    ["z", normal.z],
  ];
  const [axis, value] = components.reduce((best, current) =>
    Math.abs(current[1]) > Math.abs(best[1]) ? current : best,
  );
  return { axis, sign: value >= 0 ? "+" : "-" };
}

export function RegionOverlay({
  active,
  pick,
  modelSize,
  bodyId,
  onRegion,
}: RegionOverlayProps) {
  const surface = useRef<ReturnType<typeof dominantAxis> | null>(null);
  const offset = useRef(0);
  const world = useRef<[number, number][]>([]);
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
        surface.current = dominantAxis(hit.normal);
        offset.current = hit.point[surface.current.axis];
      }
      // The two axes that are not the surface normal, in x,y,z order — the plane the
      // outline lives in, exactly as the API expects it.
      const plane = AXES.filter((axis) => axis !== surface.current!.axis);
      return { x, y, hit: [hit.point[plane[0]], hit.point[plane[1]]] as [number, number] };
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
    let path = world.current;
    const face = surface.current;
    if (path.length < 2 || !face || !modelSize) {
      setScreen([]);
      onRegion(null);
      return;
    }
    const xs = path.map((p) => p[0]);
    const ys = path.map((p) => p[1]);
    const [minX, maxX] = [Math.min(...xs), Math.max(...xs)];
    const [minY, maxY] = [Math.min(...ys), Math.max(...ys)];
    if (maxX - minX < 0.2 || maxY - minY < 0.2) {
      setScreen([]); // a tap, not an outline
      onRegion(null);
      return;
    }
    if (path.length < 3) {
      // A straight drag is a rubber-band rectangle — what a mouse naturally draws.
      path = [
        [minX, minY],
        [maxX, minY],
        [maxX, maxY],
        [minX, maxY],
      ];
    }
    // Reach through the whole thickness under the outline, so anything cut or raised
    // there is inside the region by construction.
    const thickness = Math.max(modelSize[face.axis] * 2, 1);
    const region: LassoRegion = {
      kind: "lasso",
      axis: face.axis,
      offset_mm: offset.current,
      depth_mm: thickness,
      points_mm: path.slice(0, 256) as [number, number][],
    };
    onRegion({
      region,
      target: bodyId,
      surface_axis: face.axis,
      surface_sign: face.sign,
    });
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
        {screen.length > 1 && (
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
          : screen.length
            ? "region set — now say what belongs there"
            : "draw around the area you want to change"}
      </span>
    </div>
  );
}
