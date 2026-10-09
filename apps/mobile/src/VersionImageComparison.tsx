import { useMemo, useRef, useState } from "react";
import { Image, PanResponder, Text, View } from "react-native";

import { colors, styles } from "./theme";

export function VersionImageComparison({
  beforeUrl,
  currentUrl,
  beforeLabel,
  currentLabel,
  height = 220,
}: {
  beforeUrl: string | null;
  currentUrl: string | null;
  beforeLabel: string;
  currentLabel: string;
  height?: number;
}) {
  const [ratio, setRatio] = useState(0.5);
  const [containerWidth, setContainerWidth] = useState(1);
  const width = useRef(1);
  const responder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderGrant: (event) =>
          setRatio(Math.max(0.04, Math.min(0.96, event.nativeEvent.locationX / width.current))),
        onPanResponderMove: (event) =>
          setRatio(Math.max(0.04, Math.min(0.96, event.nativeEvent.locationX / width.current))),
      }),
    [],
  );

  return (
    <View
      {...responder.panHandlers}
      accessibilityLabel={`${beforeLabel} и ${currentLabel}. Перетащите разделитель для сравнения`}
      onLayout={(event) => {
        const next = Math.max(event.nativeEvent.layout.width, 1);
        width.current = next;
        setContainerWidth(next);
      }}
      style={{ height, borderRadius: 10, overflow: "hidden", backgroundColor: colors.viewport, borderColor: colors.border, borderWidth: 1 }}
    >
      {beforeUrl ? (
        <Image source={{ uri: beforeUrl }} resizeMode="cover" style={{ position: "absolute", inset: 0 }} />
      ) : (
        <View style={{ position: "absolute", inset: 0, alignItems: "center", justifyContent: "center" }}>
          <Text style={styles.muted}>Нет preview исходной версии</Text>
        </View>
      )}
      <View style={{ position: "absolute", inset: 0, width: `${ratio * 100}%`, overflow: "hidden" }}>
        {currentUrl ? (
          <Image source={{ uri: currentUrl }} resizeMode="cover" style={{ width: containerWidth, height: "100%" }} />
        ) : (
          <View style={{ width: containerWidth, height: "100%", backgroundColor: colors.panel2 }} />
        )}
      </View>
      <View style={{ position: "absolute", left: `${ratio * 100}%`, top: 0, bottom: 0, width: 3, marginLeft: -1.5, backgroundColor: colors.accent }} />
      <View style={{ position: "absolute", top: 8, left: 8 }}><View style={styles.chip}><Text style={styles.chipText}>{currentLabel}</Text></View></View>
      <View style={{ position: "absolute", top: 8, right: 8 }}><View style={styles.chip}><Text style={styles.chipText}>{beforeLabel}</Text></View></View>
    </View>
  );
}
