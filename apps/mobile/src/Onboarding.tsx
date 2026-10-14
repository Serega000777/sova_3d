/** Full-screen first-run story shown before authentication. */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Animated,
  Easing,
  Image,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors } from "@/src/theme";

// Bump when the story materially changes so existing installs can see the new flow once.
const KEY = "sova.onboarded.v4";
const IMAGES = [
  require("../assets/onboarding/sova-night-villa-v2.png") as number,
  require("../assets/onboarding/sova-wireframe-villa-v2.png") as number,
  require("../assets/onboarding/sova-tablet-studio-v2.png") as number,
] as const;

export function Onboarding({
  language,
  onComplete,
  onSignIn,
}: {
  language: "ru" | "en";
  onComplete?: () => void;
  onSignIn?: () => void;
}) {
  const [visible, setVisible] = useState(false);
  const [step, setStep] = useState(0);
  const progress = useRef(new Animated.Value(0)).current;
  const transitionRunning = useRef(false);
  const { width } = useWindowDimensions();
  const ru = language === "ru";

  useEffect(() => {
    let active = true;
    void AsyncStorage.getItem(KEY)
      .then((value) => {
        if (active && !value) setVisible(true);
      })
      .catch(() => {
        // A storage failure must never block the app behind a repeated welcome.
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    // Resolve and decode all local backgrounds while the first slide is visible.
    // Keeping every image mounted avoids a decode/layout hitch on the first swipe.
    for (const source of IMAGES) {
      const uri = Image.resolveAssetSource(source)?.uri;
      if (uri) void Image.prefetch(uri).catch(() => undefined);
    }
  }, []);

  const finish = (action?: () => void) => {
    setVisible(false);
    void AsyncStorage.setItem(KEY, "1")
      .catch(() => undefined)
      .finally(() => action?.());
  };

  const goTo = useCallback(
    (nextStep: number) => {
      const target = Math.max(0, Math.min(IMAGES.length - 1, nextStep));
      if (target === step || transitionRunning.current) return;

      transitionRunning.current = true;
      setStep(target);
      Animated.timing(progress, {
        toValue: target,
        duration: 520,
        easing: Easing.bezier(0.22, 1, 0.36, 1),
        useNativeDriver: true,
      }).start(() => {
        transitionRunning.current = false;
      });
    },
    [progress, step],
  );

  const next = () => {
    if (step < IMAGES.length - 1) goTo(step + 1);
    else finish(onComplete);
  };

  return (
    <Modal visible={visible} animationType="fade" presentationStyle="fullScreen" onRequestClose={() => finish(onComplete)}>
      <SafeAreaView style={s.safeArea} edges={["top", "bottom"]}>
        <View style={s.stage}>
          {IMAGES.map((source, index) => {
            const inputRange = [index - 1, index, index + 1];
            const opacity = progress.interpolate({
              inputRange,
              outputRange: [0, 1, 0],
              extrapolate: "clamp",
            });
            const translateX = progress.interpolate({
              inputRange,
              outputRange: [width * 0.08, 0, -width * 0.08],
              extrapolate: "clamp",
            });

            return (
              <Animated.View
                key={index}
                pointerEvents={index === step ? "auto" : "none"}
                style={[s.animatedSlide, { opacity, transform: [{ translateX }] }]}
              >
                <Image source={source} style={s.background} resizeMode="cover" fadeDuration={0} />
                <View pointerEvents="none" style={s.blackVeil} />
                <View pointerEvents="none" style={s.topShade} />
                <View pointerEvents="none" style={s.bottomShade} />

                {index === 0 ? (
                  <FirstSlide ru={ru} />
                ) : index === 1 ? (
                  <SecondSlide ru={ru} />
                ) : (
                  <ThirdSlide ru={ru} onStart={() => finish(onComplete)} onSignIn={() => finish(onSignIn)} />
                )}
              </Animated.View>
            );
          })}

          {step < 2 && (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={ru ? "Далее" : "Next"}
              style={s.nextCircle}
              onPress={next}
            >
              <Text style={s.nextArrow}>→</Text>
            </Pressable>
          )}

          <View style={s.dots}>
            {IMAGES.map((_, index) => (
              <Pressable
                key={index}
                accessibilityRole="button"
                accessibilityLabel={`${index + 1} / ${IMAGES.length}`}
                hitSlop={8}
                onPress={() => goTo(index)}
              >
                <View style={[s.dot, index === step && s.dotActive]} />
              </Pressable>
            ))}
          </View>
        </View>
      </SafeAreaView>
    </Modal>
  );
}

function FirstSlide({ ru }: { ru: boolean }) {
  return (
    <View style={s.slide}>
      <View style={s.firstBrand}>
        <Text style={s.cubeMark}>⬡</Text>
        <Text style={s.logo}>Sova <Text style={s.orange}>3d</Text></Text>
        <Text style={s.logoNote}>{ru ? "Твои идеи\nв реальный 3D мир" : "Your ideas\ninto a real 3D world"}</Text>
      </View>

      <View style={s.firstManifesto}>
        <View style={s.manifestoLine} />
        <Text style={s.manifestoText}>
          {ru ? "Проектируй.\nВизуализируй.\nВоплощай." : "Design.\nVisualize.\nBuild."}
        </Text>
      </View>
    </View>
  );
}

function SecondSlide({ ru }: { ru: boolean }) {
  return (
    <View style={s.slide}>
      <View style={s.copyTop}>
        <Text style={s.title}>{ru ? "Создавай" : "Create"}</Text>
        <Text style={[s.title, s.orange]}>{ru ? "без границ" : "without limits"}</Text>
        <Text style={s.subtitle}>
          {ru
            ? "Моделируй дома, интерьеры,\nэкстерьеры и целые миры\nс помощью AI."
            : "Model homes, interiors,\nexteriors and whole worlds\nwith AI."}
        </Text>
      </View>

      <View style={s.toolPalette}>
        {(["⬡", "△", "♧", "▱"] as const).map((icon, index) => (
          <View key={icon} style={s.toolCell}>
            <Text style={[s.toolIcon, index === 0 && s.toolIconActive]}>{icon}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

function ThirdSlide({
  ru,
  onStart,
  onSignIn,
}: {
  ru: boolean;
  onStart: () => void;
  onSignIn: () => void;
}) {
  return (
    <View style={s.slide}>
      <View style={s.copyTop}>
        <Text style={s.title}>{ru ? "Воплощай" : "Bring"}</Text>
        <Text style={[s.title, s.orange]}>{ru ? "свои идеи" : "ideas to life"}</Text>
        <Text style={s.subtitle}>
          {ru
            ? "От идеи до готового проекта —\nбыстро, просто, профессионально."
            : "From an idea to a finished project —\nfast, simple, professional."}
        </Text>
      </View>

      <View style={s.finalActions}>
        <Pressable accessibilityRole="button" style={s.startButton} onPress={onStart}>
          <Text style={s.startButtonText}>{ru ? "Начать сейчас" : "Start now"}</Text>
          <Text style={s.startButtonArrow}>→</Text>
        </Pressable>
        <Pressable accessibilityRole="button" hitSlop={10} onPress={onSignIn}>
          <Text style={s.signInLink}>{ru ? "Войти" : "Sign in"}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#050607" },
  stage: { flex: 1, minHeight: 620, overflow: "hidden", backgroundColor: "#050607" },
  animatedSlide: { ...StyleSheet.absoluteFill },
  background: { ...StyleSheet.absoluteFill, width: "100%", height: "100%" },
  blackVeil: { ...StyleSheet.absoluteFill, backgroundColor: "rgba(0,0,0,0.10)" },
  topShade: {
    position: "absolute",
    top: 0,
    right: 0,
    left: 0,
    height: "35%",
    backgroundColor: "rgba(2,3,4,0.24)",
  },
  bottomShade: {
    position: "absolute",
    right: 0,
    bottom: 0,
    left: 0,
    height: "27%",
    backgroundColor: "rgba(2,3,4,0.62)",
  },
  slide: { flex: 1, paddingHorizontal: 28 },
  firstBrand: { alignItems: "center", paddingTop: 40 },
  cubeMark: { color: colors.accent, fontSize: 66, lineHeight: 69, fontWeight: "400" },
  logo: { marginTop: -3, color: "#ffffff", fontSize: 38, lineHeight: 44, fontWeight: "800", letterSpacing: -1.3 },
  orange: { color: colors.accent },
  logoNote: { marginTop: 7, color: "#e4e4e4", fontSize: 16, lineHeight: 22, textAlign: "center" },
  firstManifesto: {
    position: "absolute",
    left: 28,
    bottom: 93,
    flexDirection: "row",
    alignItems: "stretch",
    gap: 12,
  },
  manifestoLine: { width: 4, borderRadius: 2, backgroundColor: colors.accent },
  manifestoText: { color: "#ffffff", fontSize: 17, lineHeight: 24, fontWeight: "500" },
  copyTop: { paddingTop: 48 },
  title: { color: "#ffffff", fontSize: 34, lineHeight: 39, fontWeight: "800", letterSpacing: -1 },
  subtitle: { marginTop: 13, color: "#f0f0f0", fontSize: 16, lineHeight: 23, fontWeight: "400" },
  toolPalette: {
    position: "absolute",
    top: 164,
    right: 22,
    width: 58,
    paddingVertical: 5,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.22)",
    borderRadius: 10,
    backgroundColor: "rgba(17,18,20,0.86)",
  },
  toolCell: { height: 49, alignItems: "center", justifyContent: "center" },
  toolIcon: { color: "#e4e5e6", fontSize: 24, fontWeight: "500" },
  toolIconActive: { color: colors.accent },
  nextCircle: {
    position: "absolute",
    right: 26,
    bottom: 23,
    width: 64,
    height: 64,
    borderWidth: 1.5,
    borderColor: colors.accent,
    borderRadius: 32,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(8,9,10,0.68)",
  },
  nextArrow: { color: colors.accent, fontSize: 36, lineHeight: 39, fontWeight: "300" },
  dots: {
    position: "absolute",
    left: 31,
    bottom: 47,
    flexDirection: "row",
    alignItems: "center",
    gap: 9,
  },
  dot: { width: 7, height: 7, borderRadius: 4, backgroundColor: "#3a3b3e" },
  dotActive: { width: 15, backgroundColor: colors.accent },
  finalActions: {
    position: "absolute",
    right: 27,
    bottom: 58,
    left: 27,
    alignItems: "center",
    gap: 17,
  },
  startButton: {
    width: "100%",
    minHeight: 58,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 29,
    backgroundColor: colors.accent,
  },
  startButtonText: { color: "#1b0c04", fontSize: 17, fontWeight: "800" },
  startButtonArrow: { position: "absolute", right: 24, color: "#1b0c04", fontSize: 27, fontWeight: "500" },
  signInLink: { color: "#d9d9da", fontSize: 15, fontWeight: "500" },
});
