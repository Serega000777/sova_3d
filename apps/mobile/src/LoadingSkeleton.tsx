import { useEffect, useRef, useState } from "react";
import { AccessibilityInfo, Animated, type StyleProp, type ViewStyle } from "react-native";

import { colors } from "@/src/theme";

/** Structural loading placeholder. Motion is limited to the active request and respects Reduce Motion. */
export function LoadingSkeleton({
  style,
  accessibilityLabel,
}: {
  style?: StyleProp<ViewStyle>;
  accessibilityLabel?: string;
}) {
  const opacity = useRef(new Animated.Value(0.42)).current;
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    let active = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((enabled) => {
      if (active) setReduceMotion(enabled);
    });
    const subscription = AccessibilityInfo.addEventListener("reduceMotionChanged", setReduceMotion);
    return () => {
      active = false;
      subscription.remove();
    };
  }, []);

  useEffect(() => {
    if (reduceMotion) {
      opacity.stopAnimation();
      opacity.setValue(0.58);
      return;
    }
    const pulse = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.76, duration: 620, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.42, duration: 620, useNativeDriver: true }),
      ]),
    );
    pulse.start();
    return () => pulse.stop();
  }, [opacity, reduceMotion]);

  return (
    <Animated.View
      accessible={Boolean(accessibilityLabel)}
      accessibilityLabel={accessibilityLabel}
      accessibilityRole={accessibilityLabel ? "progressbar" : undefined}
      style={[{ backgroundColor: colors.panel2, opacity }, style]}
    />
  );
}

export function ProjectLibrarySkeleton({ compact = false }: { compact?: boolean }) {
  return (
    <Animated.View
      accessible={false}
      style={{ gap: 10, paddingVertical: 4 }}
    >
      <LoadingSkeleton style={{ width: 112, height: 22, borderRadius: 7 }} accessibilityLabel="Загружаем проекты" />
      {[0, 1, 2].map((item) => (
        <Animated.View
          key={item}
          accessible={false}
          style={{
            minHeight: compact ? 92 : 112,
            padding: 9,
            borderRadius: 10,
            borderWidth: 1,
            borderColor: colors.border,
            flexDirection: "row",
            alignItems: "center",
            gap: 12,
          }}
        >
          <LoadingSkeleton style={{ width: compact ? 98 : 118, height: compact ? 72 : 92, borderRadius: 7 }} />
          <Animated.View accessible={false} style={{ flex: 1, gap: 10 }}>
            <LoadingSkeleton style={{ width: "72%", height: 16, borderRadius: 5 }} />
            <LoadingSkeleton style={{ width: "46%", height: 12, borderRadius: 5 }} />
          </Animated.View>
        </Animated.View>
      ))}
    </Animated.View>
  );
}

export function MarketplaceSkeleton({ columns = 1 }: { columns?: number }) {
  const width = columns === 1 ? "100%" : columns === 2 ? "48%" : "31.5%";
  return (
    <Animated.View accessible={false} style={{ flexDirection: "row", flexWrap: "wrap", gap: 12 }}>
      {Array.from({ length: columns * 2 }, (_, item) => (
        <Animated.View
          key={item}
          accessible={false}
          style={{ width, overflow: "hidden", borderRadius: 18, borderWidth: 1, borderColor: colors.border }}
        >
          <LoadingSkeleton style={{ width: "100%", height: 150, borderRadius: 0 }} accessibilityLabel={item === 0 ? "Загружаем каталог" : undefined} />
          <Animated.View accessible={false} style={{ padding: 14, gap: 10 }}>
            <LoadingSkeleton style={{ width: "76%", height: 16, borderRadius: 5 }} />
            <LoadingSkeleton style={{ width: "44%", height: 12, borderRadius: 5 }} />
            <LoadingSkeleton style={{ width: "100%", height: 40, borderRadius: 10 }} />
          </Animated.View>
        </Animated.View>
      ))}
    </Animated.View>
  );
}
