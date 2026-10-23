import { useEffect, useMemo, useRef, useState } from "react";
import { Image, Pressable, Text, View, type GestureResponderEvent } from "react-native";
import Svg, { Circle, G, Path } from "react-native-svg";

import { colors, styles } from "@/src/theme";

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

export interface MaskFramePreview {
  sequenceNo: number;
  uri: string;
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
  disabled = false,
}: {
  frames: MaskFramePreview[];
  value: FrameMaskCorrection[];
  onChange: (value: FrameMaskCorrection[]) => void;
  disabled?: boolean;
}) {
  const [selected, setSelected] = useState(frames[0]?.sequenceNo ?? 0);
  const [mode, setMode] = useState<"add" | "remove">("add");
  const [radius, setRadius] = useState(0.04);
  const [draft, setDraft] = useState<ManualMaskStroke | null>(null);
  const [aspectRatio, setAspectRatio] = useState(4 / 3);
  const drawing = useRef(false);
  const frame = frames.find((item) => item.sequenceNo === selected) ?? frames[0];
  const strokes = value.find((item) => item.sequence_no === frame?.sequenceNo)?.strokes ?? [];
  const visibleStrokes = useMemo(() => (draft ? [...strokes, draft] : strokes), [draft, strokes]);

  useEffect(() => {
    if (!frame) return;
    Image.getSize(
      frame.uri,
      (width, height) => setAspectRatio(width > 0 && height > 0 ? width / height : 4 / 3),
      () => setAspectRatio(4 / 3),
    );
  }, [frame]);

  if (!frame) return null;

  function point(event: GestureResponderEvent): MaskPoint {
    const { locationX, locationY } = event.nativeEvent;
    return {
      x: Math.max(0, Math.min(1, locationX / canvasSize.current.width)),
      y: Math.max(0, Math.min(1, locationY / canvasSize.current.height)),
    };
  }

  const canvasSize = useRef({ width: 1, height: 1 });

  function replaceCurrent(nextStrokes: ManualMaskStroke[]) {
    const others = value.filter((item) => item.sequence_no !== frame.sequenceNo);
    onChange(
      nextStrokes.length
        ? [...others, { sequence_no: frame.sequenceNo, strokes: nextStrokes }].sort(
            (a, b) => a.sequence_no - b.sequence_no,
          )
        : others,
    );
  }

  function finish() {
    if (draft?.points.length) replaceCurrent([...strokes, draft]);
    setDraft(null);
    drawing.current = false;
  }

  return (
    <View style={[styles.card, { gap: 10 }]} accessibilityLabel="Ручная коррекция маски">
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={[styles.text, { fontWeight: "700" }]}>Ручная коррекция маски</Text>
          <Text style={styles.muted}>Оранжевое добавляет объект, тёмное исключает фон после U²-Net.</Text>
        </View>
        <Text style={styles.chipText}>Кадр {frame.sequenceNo + 1}</Text>
      </View>

      <View
        style={{ width: "100%", aspectRatio, position: "relative", backgroundColor: colors.viewport, borderRadius: 10, overflow: "hidden" }}
        onLayout={(event) => {
          canvasSize.current = {
            width: Math.max(1, event.nativeEvent.layout.width),
            height: Math.max(1, event.nativeEvent.layout.height),
          };
        }}
        onStartShouldSetResponder={() => !disabled && strokes.length < 64}
        onMoveShouldSetResponder={() => !disabled}
        onResponderGrant={(event) => {
          drawing.current = true;
          setDraft({ mode, radius, points: [point(event)] });
        }}
        onResponderMove={(event) => {
          if (!drawing.current) return;
          const next = point(event);
          setDraft((current) => {
            if (!current || current.points.length >= 512) return current;
            const last = current.points.at(-1);
            if (last && Math.hypot(next.x - last.x, next.y - last.y) < 0.003) return current;
            return { ...current, points: [...current.points, next] };
          });
        }}
        onResponderRelease={finish}
        onResponderTerminate={() => {
          drawing.current = false;
          setDraft(null);
        }}
      >
        <Image source={{ uri: frame.uri }} style={{ width: "100%", height: "100%" }} resizeMode="stretch" />
        <Svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: "absolute", inset: 0 }} pointerEvents="none">
          {visibleStrokes.map((stroke, index) => {
            const color = stroke.mode === "add" ? "rgba(255,109,0,0.72)" : "rgba(12,15,20,0.78)";
            const first = stroke.points[0];
            return (
              <G key={`stroke-${index}`}>
                <Path
                  d={pathFor(stroke.points)}
                  fill="none"
                  stroke={color}
                  strokeWidth={stroke.radius * 200}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                {first && <Circle cx={first.x * 100} cy={first.y * 100} r={stroke.radius * 100} fill={color} />}
              </G>
            );
          })}
        </Svg>
      </View>

      <View style={styles.row}>
        <Pressable style={[styles.button, mode === "add" && styles.buttonPrimary]} onPress={() => setMode("add")} disabled={disabled}>
          <Text style={styles.buttonText}>Добавить</Text>
        </Pressable>
        <Pressable style={[styles.button, mode === "remove" && styles.buttonPrimary]} onPress={() => setMode("remove")} disabled={disabled}>
          <Text style={styles.buttonText}>Удалить</Text>
        </Pressable>
        {[0.02, 0.04, 0.08].map((size) => (
          <Pressable key={size} style={[styles.button, radius === size && styles.buttonPrimary]} onPress={() => setRadius(size)} disabled={disabled}>
            <Text style={styles.buttonText}>{Math.round(size * 100)}%</Text>
          </Pressable>
        ))}
        <Pressable style={styles.button} onPress={() => replaceCurrent(strokes.slice(0, -1))} disabled={disabled || !strokes.length}>
          <Text style={styles.buttonText}>Отменить штрих</Text>
        </Pressable>
        <Pressable
          style={styles.button}
          disabled={disabled || !strokes.length || frames.length < 2}
          onPress={() => onChange(frames.map((item) => ({ sequence_no: item.sequenceNo, strokes: strokes.map((stroke) => ({ ...stroke, points: stroke.points.map((entry) => ({ ...entry })) })) })))}
        >
          <Text style={styles.buttonText}>Ко всем ({frames.length})</Text>
        </Pressable>
      </View>

      <View style={styles.row}>
        {frames.map((item) => {
          const count = value.find((entry) => entry.sequence_no === item.sequenceNo)?.strokes.length ?? 0;
          return (
            <Pressable key={item.sequenceNo} style={[styles.button, item.sequenceNo === frame.sequenceNo && styles.buttonPrimary]} onPress={() => setSelected(item.sequenceNo)} disabled={disabled}>
              <Text style={styles.buttonText}>#{item.sequenceNo + 1}{count ? ` · ${count}` : ""}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}
