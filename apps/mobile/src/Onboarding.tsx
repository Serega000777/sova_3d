/** Sova's first-run story: real product imagery with native, accessible controls. */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useEffect, useState } from "react";
import { Image, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useIsTablet } from "@/src/layout";
import { colors, styles } from "@/src/theme";

const KEY = "sova.onboarded.v2";
const HERO = require("../assets/onboarding/orange-maker-caddy.png") as number;

type SlideKind = "idea" | "edit" | "export";

interface Slide {
  kind: SlideKind;
  number: string;
  title: string;
  note: string;
  actions: readonly string[];
}

const SLIDES: Record<"ru" | "en", readonly Slide[]> = {
  ru: [
    {
      kind: "idea",
      number: "01",
      title: "От идеи к модели",
      note: "Опишите предмет, добавьте фото или снимите его камерой — Sova соберёт редактируемую 3D-модель.",
      actions: ["По описанию", "С камерой"],
    },
    {
      kind: "edit",
      number: "02",
      title: "Меняйте точно",
      note: "Выбирайте детали прямо на модели, задавайте размеры в миллиметрах и сохраняйте каждое изменение.",
      actions: ["Выделение области", "Точные размеры", "Слои и история"],
    },
    {
      kind: "export",
      number: "03",
      title: "Подготовьте к печати",
      note: "Проверьте геометрию и экспортируйте модель в нужном формате без потери масштаба.",
      actions: ["Проверка модели"],
    },
  ],
  en: [
    {
      kind: "idea",
      number: "01",
      title: "From idea to model",
      note: "Describe an object, add photos or capture it — Sova builds an editable 3D model.",
      actions: ["From a description", "With the camera"],
    },
    {
      kind: "edit",
      number: "02",
      title: "Edit with precision",
      note: "Select details on the model, enter millimetres and keep every change in history.",
      actions: ["Area selection", "Exact dimensions", "Layers and history"],
    },
    {
      kind: "export",
      number: "03",
      title: "Prepare for production",
      note: "Check the geometry and export in the format you need without losing scale.",
      actions: ["Model check"],
    },
  ],
};

const ACTION_ICONS: Record<SlideKind, readonly string[]> = {
  idea: ["▤", "◉"],
  edit: ["↖", "↔", "▱"],
  export: ["✓"],
};

export function Onboarding({ language }: { language: "ru" | "en" }) {
  const isTablet = useIsTablet();
  const [visible, setVisible] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    let active = true;
    void AsyncStorage.getItem(KEY)
      .then((value) => {
        if (active && !value) setVisible(true);
      })
      .catch(() => {
        // If storage cannot be read, do not show a welcome that may nag on every launch.
      });
    return () => {
      active = false;
    };
  }, []);

  const finish = () => {
    setVisible(false);
    void AsyncStorage.setItem(KEY, "1").catch(() => {
      // If storage cannot be written, the welcome may appear again on the next launch.
    });
  };

  const slides = SLIDES[language];
  const slide = slides[step] as Slide;
  const last = step === slides.length - 1;
  const ru = language === "ru";

  return (
    <ModalScreen visible={visible} onClose={finish}>
      <View style={local.topBar}>
        <View style={local.brandRow}>
          <Text style={local.brandMark}>⬡</Text>
          <Text style={local.brand}>Sova <Text style={local.brandAccent}>3d</Text></Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={ru ? "Пропустить приветствие" : "Skip welcome"}
          hitSlop={12}
          onPress={finish}
        >
          <Text style={local.skip}>{ru ? "Пропустить" : "Skip"}</Text>
        </Pressable>
      </View>

      <ScrollView
        style={local.scroll}
        contentContainerStyle={[local.stage, isTablet && local.stageTablet]}
        showsVerticalScrollIndicator={false}
      >
        <HeroVisual kind={slide.kind} isTablet={isTablet} />

        <View style={[local.story, isTablet && local.storyTablet]}>
          <View style={local.stepRow}>
            <Text style={local.stepNumber}>{slide.number}</Text>
            <View style={local.stepDivider} />
            <Text style={local.stepTotal}>03</Text>
          </View>
          <Text style={[local.title, isTablet && local.titleTablet]}>{slide.title}</Text>
          <Text style={local.note}>{slide.note}</Text>

          <View style={local.actions}>
            {slide.actions.map((action, index) => (
              <View key={action} style={local.actionRow}>
                <View style={local.actionIcon}>
                  <Text style={local.actionIconText}>{ACTION_ICONS[slide.kind][index]}</Text>
                </View>
                <Text style={local.actionText}>{action}</Text>
                <Text style={local.actionArrow}>›</Text>
              </View>
            ))}
          </View>

          {slide.kind === "export" && (
            <View style={local.formats}>
              {(["STL", "3MF", "GLB"] as const).map((format, index) => (
                <View key={format} style={[local.format, index === 0 && local.formatActive]}>
                  <Text style={[local.formatText, index === 0 && local.formatTextActive]}>{format}</Text>
                </View>
              ))}
            </View>
          )}
        </View>
      </ScrollView>

      <View style={[local.footer, isTablet && local.footerTablet]}>
        <View style={local.dots} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
          {slides.map((_, index) => (
            <Pressable
              key={index}
              accessibilityRole="button"
              accessibilityLabel={`${index + 1} / ${slides.length}`}
              onPress={() => setStep(index)}
            >
              <View style={[local.dot, index === step && local.dotActive]} />
            </Pressable>
          ))}
        </View>
        <Pressable
          accessibilityRole="button"
          style={[styles.button, styles.buttonPrimary, local.next]}
          onPress={() => (last ? finish() : setStep((current) => current + 1))}
        >
          <Text style={local.nextText}>
            {last ? (ru ? "Начать работу" : "Get started") : ru ? "Далее" : "Next"}
          </Text>
        </Pressable>
      </View>
    </ModalScreen>
  );
}

function ModalScreen({
  visible,
  onClose,
  children,
}: {
  visible: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <Modal visible={visible} animationType="fade" presentationStyle="fullScreen" onRequestClose={onClose}>
      <SafeAreaView style={local.screen}>{children}</SafeAreaView>
    </Modal>
  );
}

function HeroVisual({ kind, isTablet }: { kind: SlideKind; isTablet: boolean }) {
  return (
    <View style={[local.visual, isTablet && local.visualTablet]}>
      <View pointerEvents="none" style={local.grid}>
        {[18, 34, 50, 66, 82].map((position) => (
          <View key={`h-${position}`} style={[local.gridHorizontal, { top: `${position}%` }]} />
        ))}
        {[18, 34, 50, 66, 82].map((position) => (
          <View key={`v-${position}`} style={[local.gridVertical, { left: `${position}%` }]} />
        ))}
      </View>
      <View style={local.orangeGlow} />
      <Image source={HERO} style={local.heroImage} resizeMode="contain" />

      {kind === "edit" && (
        <>
          <View style={local.measureLine} />
          <View style={local.measureStart} />
          <View style={local.measureEnd} />
          <View style={local.measureChip}>
            <Text style={local.measureText}>124 мм</Text>
          </View>
        </>
      )}
      {kind === "export" && (
        <View style={local.readyChip}>
          <Text style={local.readyCheck}>✓</Text>
          <View>
            <Text style={local.readyTitle}>Геометрия проверена</Text>
            <Text style={local.readyCopy}>Масштаб 1:1 · без ошибок</Text>
          </View>
        </View>
      )}
      {kind === "idea" && (
        <View style={local.modelChip}>
          <Text style={local.modelChipIcon}>⬡</Text>
          <View>
            <Text style={local.readyTitle}>Новая модель</Text>
            <Text style={local.readyCopy}>редактируемая 3D-геометрия</Text>
          </View>
        </View>
      )}
    </View>
  );
}

const local = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  topBar: {
    minHeight: 58,
    paddingHorizontal: 22,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  brandMark: { color: colors.accent, fontSize: 24, lineHeight: 28, fontWeight: "900" },
  brand: { color: colors.text, fontSize: 17, fontWeight: "800", letterSpacing: -0.4 },
  brandAccent: { color: colors.accent },
  skip: { color: colors.muted, fontSize: 14, paddingVertical: 10 },
  scroll: { flex: 1 },
  stage: { flexGrow: 1, paddingHorizontal: 20, paddingBottom: 16, gap: 18 },
  stageTablet: { flexDirection: "row", alignItems: "stretch", paddingHorizontal: 28, gap: 0 },
  visual: {
    minHeight: 310,
    flex: 1.12,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: "#242527",
    borderRadius: 24,
    backgroundColor: colors.viewport,
  },
  visualTablet: { minHeight: 0, borderTopRightRadius: 0, borderBottomRightRadius: 0 },
  grid: { position: "absolute", top: 0, right: 0, bottom: 0, left: 0, opacity: 0.48 },
  gridHorizontal: { position: "absolute", left: 0, right: 0, height: 1, backgroundColor: "#1c1d1f" },
  gridVertical: { position: "absolute", top: 0, bottom: 0, width: 1, backgroundColor: "#1c1d1f" },
  orangeGlow: {
    position: "absolute",
    width: 260,
    height: 260,
    borderRadius: 130,
    right: "8%",
    bottom: "8%",
    backgroundColor: colors.accentWash,
    transform: [{ scaleX: 1.35 }],
  },
  heroImage: { width: "100%", height: "100%", transform: [{ scale: 1.06 }] },
  story: { flex: 0.88, gap: 12, paddingHorizontal: 4 },
  storyTablet: {
    justifyContent: "center",
    paddingHorizontal: 32,
    paddingVertical: 26,
    borderWidth: 1,
    borderLeftWidth: 0,
    borderColor: "#242527",
    borderTopRightRadius: 24,
    borderBottomRightRadius: 24,
    backgroundColor: colors.panel,
  },
  stepRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  stepNumber: { color: colors.accent, fontSize: 26, fontWeight: "900" },
  stepDivider: { width: 18, height: 2, backgroundColor: colors.accent },
  stepTotal: { color: colors.muted, fontSize: 14, fontWeight: "700" },
  title: { color: colors.text, fontSize: 31, lineHeight: 35, fontWeight: "900", letterSpacing: -1.05 },
  titleTablet: { fontSize: 40, lineHeight: 44 },
  note: { color: colors.muted, fontSize: 15, lineHeight: 21 },
  actions: { gap: 8, marginTop: 5 },
  actionRow: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    gap: 11,
    paddingHorizontal: 11,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  actionIcon: {
    width: 31,
    height: 31,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 9,
    backgroundColor: colors.accentWashStrong,
  },
  actionIconText: { color: colors.accent, fontSize: 17, fontWeight: "800" },
  actionText: { flex: 1, color: colors.text, fontSize: 14, fontWeight: "600" },
  actionArrow: { color: colors.muted, fontSize: 22 },
  formats: { flexDirection: "row", gap: 8, marginTop: 2 },
  format: {
    flex: 1,
    minHeight: 48,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 11,
    backgroundColor: colors.panel2,
  },
  formatActive: { borderColor: colors.accent, backgroundColor: colors.accentWash },
  formatText: { color: colors.muted, fontSize: 13, fontWeight: "800" },
  formatTextActive: { color: colors.accent },
  footer: { paddingHorizontal: 20, paddingBottom: 12, gap: 13 },
  footerTablet: { flexDirection: "row", alignItems: "center", paddingHorizontal: 28 },
  dots: { flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 8 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.border },
  dotActive: { width: 25, backgroundColor: colors.accent },
  next: { minHeight: 52, flex: 1, justifyContent: "center", borderRadius: 13 },
  nextText: { color: "#160b05", fontSize: 15, fontWeight: "900" },
  measureLine: { position: "absolute", left: "22%", right: "19%", bottom: "13%", height: 1, backgroundColor: "#fff" },
  measureStart: { position: "absolute", left: "22%", bottom: "11.8%", width: 1, height: 10, backgroundColor: "#fff" },
  measureEnd: { position: "absolute", right: "19%", bottom: "11.8%", width: 1, height: 10, backgroundColor: "#fff" },
  measureChip: { position: "absolute", alignSelf: "center", bottom: "8%", paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8, backgroundColor: "rgba(8,8,9,0.82)" },
  measureText: { color: colors.text, fontSize: 12, fontWeight: "700" },
  readyChip: { position: "absolute", left: 16, right: 16, bottom: 14, flexDirection: "row", alignItems: "center", gap: 10, padding: 11, borderWidth: 1, borderColor: "rgba(255,107,26,0.46)", borderRadius: 13, backgroundColor: "rgba(14,14,15,0.88)" },
  readyCheck: { width: 30, height: 30, borderRadius: 15, overflow: "hidden", textAlign: "center", lineHeight: 30, color: "#160b05", backgroundColor: colors.accent, fontWeight: "900" },
  readyTitle: { color: colors.text, fontSize: 13, fontWeight: "800" },
  readyCopy: { color: colors.muted, fontSize: 11, marginTop: 2 },
  modelChip: { position: "absolute", left: 16, bottom: 14, flexDirection: "row", alignItems: "center", gap: 9, paddingHorizontal: 11, paddingVertical: 9, borderWidth: 1, borderColor: colors.border, borderRadius: 12, backgroundColor: "rgba(14,14,15,0.88)" },
  modelChipIcon: { color: colors.accent, fontSize: 22, fontWeight: "900" },
});
