import type { ProjectReference } from "@physical-ai/contracts";
import { useState } from "react";
import { Image, type LayoutChangeEvent, type NativeSyntheticEvent, type NativeTouchEvent, Pressable, Text, View } from "react-native";
import Svg, { Circle, Line } from "react-native-svg";

import { colors, styles } from "./theme";

type Size = { width: number; height: number };

function imageRect(reference: ProjectReference, layout: Size) {
  const scale = Math.min(layout.width / reference.width_px, layout.height / reference.height_px);
  const width = reference.width_px * scale;
  const height = reference.height_px * scale;
  return { x: (layout.width - width) / 2, y: (layout.height - height) / 2, width, height };
}

export function ReferenceViewer({
  reference,
  height = 360,
  onPoint,
}: {
  reference: ProjectReference;
  height?: number;
  onPoint: (point: [number, number]) => void;
}) {
  const [layout, setLayout] = useState<Size>({ width: 1, height });
  const rect = imageRect(reference, layout);
  const points = reference.calibration ?? [];
  const pixels = points.map(([x, y]) => [rect.x + x * rect.width, rect.y + y * rect.height] as const);

  function pick(event: NativeSyntheticEvent<NativeTouchEvent>) {
    const x = (event.nativeEvent.locationX - rect.x) / Math.max(rect.width, 1);
    const y = (event.nativeEvent.locationY - rect.y) / Math.max(rect.height, 1);
    if (x < 0 || x > 1 || y < 0 || y > 1) return;
    onPoint([x, y]);
  }

  function rememberLayout(event: LayoutChangeEvent) {
    setLayout({ width: event.nativeEvent.layout.width, height: event.nativeEvent.layout.height });
  }

  const calibrated = points.length === 2 && reference.known_mm > 0;
  return (
    <Pressable
      accessibilityLabel="Фото-референс. Нажмите две точки известного расстояния"
      onPress={pick}
      onLayout={rememberLayout}
      style={{ height, borderRadius: 10, overflow: "hidden", backgroundColor: colors.viewport }}
    >
      <Image
        source={{ uri: reference.url }}
        resizeMode="contain"
        style={{ position: "absolute", inset: 0, opacity: reference.visible ? reference.opacity : 0.12 }}
      />
      <Svg width="100%" height="100%" pointerEvents="none">
        {pixels.length === 2 && (
          <Line
            x1={pixels[0]?.[0]}
            y1={pixels[0]?.[1]}
            x2={pixels[1]?.[0]}
            y2={pixels[1]?.[1]}
            stroke={colors.accent}
            strokeWidth={3}
            strokeDasharray="7 5"
          />
        )}
        {pixels.map((point, index) => (
          <Circle
            key={index}
            cx={point[0]}
            cy={point[1]}
            r={8}
            fill={colors.accent}
            stroke={colors.text}
            strokeWidth={2}
          />
        ))}
      </Svg>
      <View style={{ position: "absolute", left: 8, bottom: 8, right: 8, gap: 6 }} pointerEvents="none">
        <View style={[styles.chip, { alignSelf: "flex-start", borderColor: calibrated ? colors.green : colors.yellow }]}>
          <Text style={[styles.chipText, { color: calibrated ? colors.green : colors.yellow }]}>
            {calibrated
              ? `Фото · масштаб задан · ${reference.width_mm.toFixed(1)} мм`
              : points.length === 0
                ? "Фото · отметьте первую точку"
                : "Фото · отметьте вторую точку"}
          </Text>
        </View>
      </View>
    </Pressable>
  );
}
