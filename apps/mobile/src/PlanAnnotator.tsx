/**
 * Mobile plan editor surface (T-237/F-087 increment 1, docs/design/MOBILE-PLAN-EDITOR.md).
 * Renders the same plan geometry as `PlanViewer.tsx` (rooms/walls/openings/nodes) plus the
 * seven in-scope annotation kinds (pin/text/rect/cloud/circle/arrow/dimension; freehand is a
 * later increment), and drives placing/selecting/moving them with one shared gesture surface.
 * Every pure annotation function (`hitTest`, `moveAnnotation`, `nextPinNumber`, `cloudPath`,
 * `formatLength`) is reused verbatim from `@physical-ai/contracts` — only rendering and the
 * touch gesture layer are new here.
 */
import {
  ANNOTATION_COLOURS,
  type Annotation,
  type AnnotationBase,
  type AnnotationKind,
  type FloorPlan,
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
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Svg, { Circle, G, Line, Path, Polygon, Polyline, Rect, Text as SvgText } from "react-native-svg";

import { type PlanEntitySelection, planEntityAtPoint, planNodes } from "./plan-link";
import { PlanTextSheet } from "./PlanToolSheet";
import { colors, styles } from "./theme";

/** Select/Pan plus the seven shippable annotation kinds; freehand is a later increment. */
export type MobilePlanTool = "select" | "pan" | Exclude<AnnotationKind, "freehand">;

const PIN_PX = 13;
const SNAP_PX = 12;
const MIN_DRAG_MM = 20;
const MOVE_THRESHOLD_MM = 3;

const TOOLS: { id: MobilePlanTool; glyph: string; labelRu: string; labelEn: string }[] = [
  { id: "select", glyph: "↖", labelRu: "Выбор", labelEn: "Select" },
  { id: "pan", glyph: "✋", labelRu: "Рука", labelEn: "Pan" },
  { id: "pin", glyph: "📍", labelRu: "Пин", labelEn: "Pin" },
  { id: "cloud", glyph: "☁", labelRu: "Облако", labelEn: "Cloud" },
  { id: "rect", glyph: "▭", labelRu: "Прям.", labelEn: "Rect" },
  { id: "circle", glyph: "◯", labelRu: "Круг", labelEn: "Circle" },
  { id: "arrow", glyph: "➚", labelRu: "Стрелка", labelEn: "Arrow" },
  { id: "text", glyph: "T", labelRu: "Текст", labelEn: "Text" },
  { id: "dimension", glyph: "↔", labelRu: "Размер", labelEn: "Dimension" },
];

let idCounter = 0;
function newId(): string {
  idCounter += 1;
  return `m${Date.now().toString(36)}${idCounter}`;
}

/** The same base fields every new annotation needs; callers outside this file use this too. */
export function makeAnnotationBase(author: string): AnnotationBase {
  return {
    id: newId(),
    author,
    created_at: new Date().toISOString(),
    status: "open",
    note: "",
    colour: ANNOTATION_COLOURS[0],
  };
}

/** Snap to the nearest wall end or room corner within tolerance — ported from PlanEditor.tsx. */
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

/** The shared two-point-drag gesture family (rect/cloud/circle/arrow/dimension) — ported from PlanEditor.tsx. */
function dragShape(base: AnnotationBase, start: Point, end: Point, kind: MobilePlanTool): Annotation | null {
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

/** One annotation's SVG body — ported 1:1 from PlanEditor.tsx's `AnnotationShape` switch. */
function AnnotationShape({ a, px, selected }: { a: Annotation; px: number; selected: boolean }) {
  const width = 2.2 * px;
  const opacity = a.status === "resolved" ? 0.4 : 1;
  let body: ReactNode = null;
  switch (a.kind) {
    case "pin":
      body = (
        <G opacity={opacity}>
          <Circle cx={a.at[0]} cy={a.at[1]} r={PIN_PX * px} fill={a.colour} stroke="#0b0d12" strokeWidth={1.5 * px} />
          <SvgText x={a.at[0]} y={a.at[1] + 4.5 * px} fontSize={13 * px} fontWeight="700" textAnchor="middle" fill="#0b0d12">
            {a.status === "resolved" ? "✓" : String(a.number)}
          </SvgText>
        </G>
      );
      break;
    case "rect":
      body = (
        <Rect
          x={Math.min(a.from[0], a.to[0])}
          y={Math.min(a.from[1], a.to[1])}
          width={Math.abs(a.to[0] - a.from[0])}
          height={Math.abs(a.to[1] - a.from[1])}
          stroke={a.colour}
          strokeWidth={width}
          fill="none"
          opacity={opacity}
        />
      );
      break;
    case "cloud":
      body = <Path d={cloudPath(a.from, a.to, 26 * px)} stroke={a.colour} strokeWidth={width} fill="none" opacity={opacity} />;
      break;
    case "circle":
      body = (
        <Circle cx={a.centre[0]} cy={a.centre[1]} r={a.radius_mm} stroke={a.colour} strokeWidth={width} fill="none" opacity={opacity} />
      );
      break;
    case "arrow": {
      const angle = Math.atan2(a.to[1] - a.from[1], a.to[0] - a.from[0]);
      const head = 12 * px;
      const left: Point = [a.to[0] - head * Math.cos(angle - 0.45), a.to[1] - head * Math.sin(angle - 0.45)];
      const right: Point = [a.to[0] - head * Math.cos(angle + 0.45), a.to[1] - head * Math.sin(angle + 0.45)];
      body = (
        <G stroke={a.colour} strokeWidth={width} fill="none" opacity={opacity}>
          <Line x1={a.from[0]} y1={a.from[1]} x2={a.to[0]} y2={a.to[1]} />
          <Polyline points={`${left.join(",")} ${a.to.join(",")} ${right.join(",")}`} strokeLinejoin="round" />
        </G>
      );
      break;
    }
    case "dimension": {
      const length = distanceBetween(a.from, a.to);
      const angle = (Math.atan2(a.to[1] - a.from[1], a.to[0] - a.from[0]) * 180) / Math.PI;
      const mid: Point = [(a.from[0] + a.to[0]) / 2, (a.from[1] + a.to[1]) / 2];
      const flip = angle > 90 || angle < -90 ? 180 : 0;
      const tick = 7 * px;
      const nx = -(a.to[1] - a.from[1]) / (length || 1);
      const ny = (a.to[0] - a.from[0]) / (length || 1);
      body = (
        <G stroke={a.colour} strokeWidth={width} fill="none" opacity={opacity}>
          <Line x1={a.from[0]} y1={a.from[1]} x2={a.to[0]} y2={a.to[1]} />
          <Line x1={a.from[0] - nx * tick} y1={a.from[1] - ny * tick} x2={a.from[0] + nx * tick} y2={a.from[1] + ny * tick} />
          <Line x1={a.to[0] - nx * tick} y1={a.to[1] - ny * tick} x2={a.to[0] + nx * tick} y2={a.to[1] + ny * tick} />
          <SvgText
            x={mid[0]}
            y={mid[1] - 6 * px}
            fontSize={13 * px}
            fill={a.colour}
            stroke="#0b0d12"
            strokeWidth={3 * px}
            textAnchor="middle"
            transform={`rotate(${angle + flip} ${mid[0]} ${mid[1]})`}
          >
            {formatLength(length)}
          </SvgText>
        </G>
      );
      break;
    }
    case "text":
      body = (
        <SvgText x={a.at[0]} y={a.at[1] + a.size_mm} fontSize={a.size_mm} fill={a.colour} stroke="#0b0d12" strokeWidth={3 * px} opacity={opacity}>
          {a.text}
        </SvgText>
      );
      break;
    case "freehand":
      body = null; // increment 2 (docs/design/MOBILE-PLAN-EDITOR.md §7)
      break;
  }
  const b = selected ? selectionBox(a, px) : null;
  return (
    <>
      {body}
      {b && (
        <Rect x={b.x} y={b.y} width={b.w} height={b.h} fill="none" stroke={colors.accent} strokeWidth={px} strokeDasharray={`${5 * px} ${4 * px}`} />
      )}
    </>
  );
}

interface View2D {
  x: number;
  y: number;
  /** Pixels per millimetre. */
  scale: number;
}

type GestureState =
  | { kind: "pan"; startView: View2D }
  | { kind: "entity-or-pan"; startView: View2D; moved: boolean }
  | { kind: "move"; id: string; original: Annotation; startPoint: Point; moved: boolean }
  | { kind: "draw"; start: Point };

export interface PlanAnnotatorProps {
  plan: FloorPlan;
  annotations: readonly Annotation[];
  /** One call per completed gesture — never per movement frame (docs/design/MOBILE-PLAN-EDITOR.md §2). */
  onChange: (next: Annotation[]) => void;
  selectedAnnotationId: string | null;
  onSelectAnnotation: (id: string | null) => void;
  tool: MobilePlanTool;
  onToolChange: (tool: MobilePlanTool) => void;
  author: string;
  language: "ru" | "en";
  /** The existing Plan↔Model cross-reference selection (room/wall/node), unchanged from PlanViewer.tsx. */
  entitySelection: PlanEntitySelection | null;
  onSelectEntity: (selection: PlanEntitySelection) => void;
  height?: number;
}

export function PlanAnnotator({
  plan,
  annotations,
  onChange,
  selectedAnnotationId,
  onSelectAnnotation,
  tool,
  onToolChange,
  author,
  language,
  entitySelection,
  onSelectEntity,
  height = 360,
}: PlanAnnotatorProps) {
  const ru = language === "ru";
  const [size, setSize] = useState({ width: 1, height: 1 });
  const [view, setView] = useState<View2D>({ x: -500, y: -500, scale: 0.08 });
  const [draft, setDraft] = useState<Annotation | null>(null);
  const [movePreview, setMovePreview] = useState<Annotation | null>(null);
  const [textDraft, setTextDraft] = useState<{ at: Point; px: number } | null>(null);
  const gesture = useRef<GestureState | null>(null);
  const pinchStart = useRef<View2D>(view);

  const fit = useCallback((p: FloorPlan, w: number, h: number) => {
    const b = planBounds(p);
    if (!b || w <= 1 || h <= 1) return;
    const spanW = Math.max(b.maxX - b.minX, 1000);
    const spanH = Math.max(b.maxY - b.minY, 1000);
    const scale = Math.min((w - 40) / spanW, (h - 40) / spanH);
    setView({ scale, x: b.minX - (w / scale - spanW) / 2, y: b.minY - (h / scale - spanH) / 2 });
  }, []);

  useEffect(() => {
    fit(plan, size.width, size.height);
    // re-frame on a new plan identity or the first real measurement, not on every resize
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan.id, size.width, size.height]);

  const px = 1 / view.scale;
  const toPlan = useCallback((x: number, y: number): Point => [view.x + x / view.scale, view.y + y / view.scale], [view]);
  const makeBase = useCallback(() => makeAnnotationBase(author), [author]);

  const pan = Gesture.Pan()
    .runOnJS(true)
    .maxPointers(1)
    .minDistance(0)
    .onStart((event) => {
      const at = toPlan(event.x, event.y);
      if (tool === "pan") {
        gesture.current = { kind: "pan", startView: view };
        return;
      }
      if (tool === "select") {
        const hit = hitTest(annotations, at, 10 * px);
        onSelectAnnotation(hit ? hit.id : null);
        gesture.current = hit
          ? { kind: "move", id: hit.id, original: hit, startPoint: at, moved: false }
          : { kind: "entity-or-pan", startView: view, moved: false };
        return;
      }
      if (tool === "pin") {
        const point = snapTo(at, plan, SNAP_PX * px);
        const next: Annotation = { ...makeBase(), kind: "pin", at: point, number: nextPinNumber(annotations) };
        onChange([...annotations, next]);
        onSelectAnnotation(next.id);
        gesture.current = null;
        return;
      }
      if (tool === "text") {
        setTextDraft({ at: snapTo(at, plan, SNAP_PX * px), px });
        gesture.current = null;
        return;
      }
      const start = snapTo(at, plan, SNAP_PX * px);
      gesture.current = { kind: "draw", start };
      setDraft(dragShape(makeBase(), start, start, tool));
    })
    .onUpdate((event) => {
      const g = gesture.current;
      if (!g) return;
      if (g.kind === "pan" || g.kind === "entity-or-pan") {
        if (g.kind === "entity-or-pan" && !g.moved && Math.hypot(event.translationX, event.translationY) > 3) {
          g.moved = true;
        }
        setView({
          scale: g.startView.scale,
          x: g.startView.x - event.translationX / g.startView.scale,
          y: g.startView.y - event.translationY / g.startView.scale,
        });
        return;
      }
      if (g.kind === "move") {
        const at = toPlan(event.x, event.y);
        const dx = at[0] - g.startPoint[0];
        const dy = at[1] - g.startPoint[1];
        if (!g.moved && Math.hypot(dx, dy) < MOVE_THRESHOLD_MM * px) return;
        g.moved = true;
        setMovePreview(moveAnnotation(g.original, dx, dy));
        return;
      }
      if (g.kind === "draw") {
        const point = snapTo(toPlan(event.x, event.y), plan, SNAP_PX * px);
        setDraft(dragShape(makeBase(), g.start, point, tool));
      }
    })
    .onEnd((event) => {
      const g = gesture.current;
      gesture.current = null;
      if (!g) return;
      if (g.kind === "entity-or-pan") {
        if (!g.moved) {
          const hit = planEntityAtPoint(plan, toPlan(event.x, event.y));
          if (hit) onSelectEntity(hit);
        }
        return;
      }
      if (g.kind === "move") {
        if (g.moved) {
          const at = toPlan(event.x, event.y);
          const dx = at[0] - g.startPoint[0];
          const dy = at[1] - g.startPoint[1];
          const moved = moveAnnotation(g.original, dx, dy);
          onChange(annotations.map((a) => (a.id === g.id ? moved : a)));
        }
        setMovePreview(null);
        return;
      }
      if (g.kind === "draw") {
        const point = snapTo(toPlan(event.x, event.y), plan, SNAP_PX * px);
        const shape = dragShape(makeBase(), g.start, point, tool);
        const big = shape
          ? shape.kind === "circle"
            ? shape.radius_mm > MIN_DRAG_MM
            : "from" in shape && distanceBetween(shape.from, shape.to) > MIN_DRAG_MM
          : false;
        if (shape && big) {
          onChange([...annotations, shape]);
          onSelectAnnotation(shape.id);
        }
        setDraft(null);
      }
    });

  const pinch = Gesture.Pinch()
    .onStart(() => {
      pinchStart.current = view;
    })
    .onUpdate((event) => {
      const start = pinchStart.current;
      const scale = Math.min(Math.max(start.scale * event.scale, 0.005), 4);
      const mx = start.x + event.focalX / start.scale;
      const my = start.y + event.focalY / start.scale;
      setView({ scale, x: mx - event.focalX / scale, y: my - event.focalY / scale });
    });

  const composed = Gesture.Simultaneous(pan, pinch);

  const submitText = (value: string) => {
    if (textDraft && value.trim()) {
      const next: Annotation = {
        ...makeBase(),
        kind: "text",
        at: textDraft.at,
        text: value.trim(),
        size_mm: 14 * textDraft.px,
      };
      onChange([...annotations, next]);
      onSelectAnnotation(next.id);
    }
    setTextDraft(null);
  };

  const rendered = annotations.map((a) => (movePreview && a.id === movePreview.id ? movePreview : a));
  const renderList = draft ? [...rendered, draft] : rendered;
  const nodes = planNodes(plan);

  return (
    <View style={{ gap: 8 }}>
      <View
        style={{ height, borderRadius: 10, overflow: "hidden", backgroundColor: colors.viewport }}
        onLayout={(event) => setSize({ width: event.nativeEvent.layout.width, height: event.nativeEvent.layout.height })}
      >
        <GestureDetector gesture={composed}>
          <View style={{ flex: 1 }}>
            <Svg width="100%" height="100%" viewBox={`${view.x} ${view.y} ${size.width / view.scale} ${size.height / view.scale}`}>
              {plan.rooms.map((room, index) => {
                const selected = entitySelection?.kind === "room" && entitySelection.index === index;
                return (
                  <Polygon
                    key={`room-${index}`}
                    points={room.outline.map((p) => p.join(",")).join(" ")}
                    fill={selected ? colors.accentWashStrong : "rgba(91,156,255,0.08)"}
                    stroke={selected ? colors.accent : "transparent"}
                    strokeWidth={selected ? Math.max(px * 3, 12) : 0}
                  />
                );
              })}
              {plan.rooms.map((room, index) => {
                const b = pointsBounds(room.outline);
                if (!b) return null;
                return (
                  <SvgText
                    key={`room-label-${index}`}
                    x={(b.minX + b.maxX) / 2}
                    y={(b.minY + b.maxY) / 2}
                    fill={colors.muted}
                    fontSize={Math.max((b.maxX - b.minX + (b.maxY - b.minY)) * 0.011, 80)}
                    textAnchor="middle"
                  >
                    {`${room.name} · ${(roomArea(room) / 1_000_000).toFixed(1)} ${ru ? "м²" : "m²"}`}
                  </SvgText>
                );
              })}
              {plan.walls.map((wall, index) => {
                const selected = entitySelection?.kind === "wall" && entitySelection.index === index;
                return (
                  <Line
                    key={`wall-${index}`}
                    x1={wall.a[0]}
                    y1={wall.a[1]}
                    x2={wall.b[0]}
                    y2={wall.b[1]}
                    stroke={selected ? colors.accent : "#8d96a6"}
                    strokeWidth={selected ? wall.thickness_mm * 1.35 : wall.thickness_mm}
                    strokeLinecap="square"
                  />
                );
              })}
              {plan.openings.map((opening, index) => {
                const wall = plan.walls[opening.wall];
                if (!wall) return null;
                const length = distanceBetween(wall.a, wall.b) || 1;
                const ux = (wall.b[0] - wall.a[0]) / length;
                const uy = (wall.b[1] - wall.a[1]) / length;
                const p0: Point = [wall.a[0] + ux * opening.offset_mm, wall.a[1] + uy * opening.offset_mm];
                const p1: Point = [p0[0] + ux * opening.width_mm, p0[1] + uy * opening.width_mm];
                const nx = -uy;
                const ny = ux;
                const half = wall.thickness_mm / 2;
                return (
                  <G key={`opening-${index}`}>
                    <Line x1={p0[0]} y1={p0[1]} x2={p1[0]} y2={p1[1]} stroke={colors.viewport} strokeWidth={wall.thickness_mm + 4 * px} />
                    {opening.kind === "window" ? (
                      <>
                        <Line
                          x1={p0[0] + nx * half * 0.5}
                          y1={p0[1] + ny * half * 0.5}
                          x2={p1[0] + nx * half * 0.5}
                          y2={p1[1] + ny * half * 0.5}
                          stroke={colors.text}
                          strokeWidth={px * 1.5}
                        />
                        <Line
                          x1={p0[0] - nx * half * 0.5}
                          y1={p0[1] - ny * half * 0.5}
                          x2={p1[0] - nx * half * 0.5}
                          y2={p1[1] - ny * half * 0.5}
                          stroke={colors.text}
                          strokeWidth={px * 1.5}
                        />
                      </>
                    ) : opening.kind === "door" ? (
                      <Line
                        x1={p0[0]}
                        y1={p0[1]}
                        x2={p0[0] + nx * opening.width_mm}
                        y2={p0[1] + ny * opening.width_mm}
                        stroke={colors.text}
                        strokeWidth={px * 1.5}
                      />
                    ) : null}
                  </G>
                );
              })}
              {nodes.map((node, index) => {
                const selected = entitySelection?.kind === "node" && entitySelection.index === index;
                return (
                  <Circle
                    key={`node-${index}`}
                    cx={node[0]}
                    cy={node[1]}
                    r={Math.max(px * (selected ? 7 : 4.5), 45)}
                    fill={selected ? colors.accent : colors.topologyVertex}
                    stroke={colors.viewport}
                    strokeWidth={Math.max(px * 2, 8)}
                  />
                );
              })}
              {renderList.map((a) => (
                <AnnotationShape key={a.id} a={a} px={px} selected={a.id === selectedAnnotationId} />
              ))}
            </Svg>
          </View>
        </GestureDetector>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, paddingVertical: 2 }}>
        {TOOLS.map((item) => {
          const active = tool === item.id;
          return (
            <Pressable
              key={item.id}
              accessibilityRole="button"
              accessibilityLabel={ru ? item.labelRu : item.labelEn}
              onPress={() => onToolChange(item.id)}
              style={[styles.chip, active && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}
            >
              <Text style={[styles.chipText, active && { color: colors.accent }]}>
                {item.glyph} {ru ? item.labelRu : item.labelEn}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>
      <PlanTextSheet
        visible={Boolean(textDraft)}
        language={language}
        onCancel={() => setTextDraft(null)}
        onSubmit={submitText}
      />
    </View>
  );
}
