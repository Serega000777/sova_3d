import {
  type FloorPlan,
  type Point,
  planBounds,
  pointsBounds,
  roomArea,
} from "@physical-ai/contracts";
import { useMemo } from "react";
import { Text, View } from "react-native";
import Svg, { Circle, Line, Polygon, Text as SvgText } from "react-native-svg";

import {
  type PlanEntitySelection,
  planNodes,
  planSelectionLabel,
  planSelectionPoints,
} from "./plan-link";
import { colors, styles } from "./theme";

function paddedViewBox(plan: FloorPlan, selection: PlanEntitySelection | null): string {
  const full = planBounds(plan) ?? { minX: 0, minY: 0, maxX: 1, maxY: 1 };
  const selected = pointsBounds(planSelectionPoints(plan, selection));
  const fullWidth = Math.max(full.maxX - full.minX, 1);
  const fullHeight = Math.max(full.maxY - full.minY, 1);
  const source = selected ?? full;
  const width = Math.max(source.maxX - source.minX, fullWidth * (selected ? 0.34 : 1));
  const height = Math.max(source.maxY - source.minY, fullHeight * (selected ? 0.34 : 1));
  const centreX = (source.minX + source.maxX) / 2;
  const centreY = (source.minY + source.maxY) / 2;
  const margin = Math.max(width, height) * 0.12;
  return `${centreX - width / 2 - margin} ${centreY - height / 2 - margin} ${width + margin * 2} ${height + margin * 2}`;
}

function polygonPoints(points: readonly Point[]): string {
  return points.map((point) => `${point[0]},${point[1]}`).join(" ");
}

export function PlanViewer({
  plan,
  selection,
  onSelect,
  height = 360,
}: {
  plan: FloorPlan;
  selection: PlanEntitySelection | null;
  onSelect: (selection: PlanEntitySelection) => void;
  height?: number;
}) {
  const nodes = useMemo(() => planNodes(plan), [plan]);
  const bounds = planBounds(plan);
  const span = bounds
    ? Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY, 1)
    : 1;
  const lineScale = span / 900;
  const label = planSelectionLabel(plan, selection);

  return (
    <View
      style={{ height, borderRadius: 10, overflow: "hidden", backgroundColor: colors.viewport }}
      accessibilityLabel="2D floor plan"
    >
      <Svg width="100%" height="100%" viewBox={paddedViewBox(plan, selection)}>
        {plan.rooms.map((room, index) => {
          const selected = selection?.kind === "room" && selection.index === index;
          return (
            <Polygon
              key={`room-${index}`}
              points={polygonPoints(room.outline)}
              fill={selected ? colors.accentWashStrong : "rgba(91,156,255,0.08)"}
              stroke={selected ? colors.accent : "transparent"}
              strokeWidth={selected ? Math.max(lineScale * 3, 12) : 0}
              onPress={() => onSelect({ kind: "room", index })}
              accessibilityLabel={`Комната ${room.name}`}
            />
          );
        })}
        {plan.rooms.map((room, index) => {
          const roomBounds = pointsBounds(room.outline);
          if (!roomBounds) return null;
          return (
            <SvgText
              key={`room-label-${index}`}
              x={(roomBounds.minX + roomBounds.maxX) / 2}
              y={(roomBounds.minY + roomBounds.maxY) / 2}
              fill={colors.muted}
              fontSize={Math.max(span * 0.022, 80)}
              textAnchor="middle"
              pointerEvents="none"
            >
              {`${room.name} · ${(roomArea(room) / 1_000_000).toFixed(1)} м²`}
            </SvgText>
          );
        })}
        {plan.walls.map((wall, index) => {
          const selected = selection?.kind === "wall" && selection.index === index;
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
              onPress={() => onSelect({ kind: "wall", index })}
              accessibilityLabel={`Стена ${index + 1}`}
            />
          );
        })}
        {nodes.map((node, index) => {
          const selected = selection?.kind === "node" && selection.index === index;
          return (
            <Circle
              key={`node-${index}`}
              cx={node[0]}
              cy={node[1]}
              r={Math.max(span * (selected ? 0.018 : 0.011), 45)}
              fill={selected ? colors.accent : colors.topologyVertex}
              stroke={colors.viewport}
              strokeWidth={Math.max(lineScale * 2, 8)}
              onPress={() => onSelect({ kind: "node", index })}
              accessibilityLabel={`Узел ${index + 1}`}
            />
          );
        })}
      </Svg>
      <View style={{ position: "absolute", left: 8, bottom: 8, gap: 6 }} pointerEvents="none">
        <View style={[styles.chip, label && { borderColor: colors.accent }]}>
          <Text style={[styles.chipText, label && { color: colors.accent }]}>2D · {label ?? plan.name}</Text>
        </View>
        <View style={styles.chip}>
          <Text style={styles.chipText}>Нажмите комнату, стену или узел</Text>
        </View>
      </View>
    </View>
  );
}
