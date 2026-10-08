/** First-run welcome: the same three product promises as the web app, sized for a phone. */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useEffect, useState } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, styles } from "@/src/theme";

const KEY = "sova.onboarded.v1";

const SLIDES = {
  ru: [
    {
      icon: "✦",
      title: "Создавайте 3D из описания, фото и сканов",
      note: "Опишите предмет, загрузите фото или отсканируйте — получите модель, которую можно редактировать.",
    },
    {
      icon: "⌂",
      title: "Сканируйте комнаты и здания",
      note: "Собирайте комнаты в план дома, снимайте фасады отдельными проходами и размечайте план пинами и облаками.",
    },
    {
      icon: "⬡",
      title: "Редактируйте точно",
      note: "Используйте сетку и привязку, правьте вершины, рёбра и грани. Экспортируйте для печати, игр и CAD.",
    },
  ],
  en: [
    {
      icon: "✦",
      title: "Create 3D from words, photos and scans",
      note: "Describe an object, upload a photo or scan it — get a model you can edit.",
    },
    {
      icon: "⌂",
      title: "Scan rooms and buildings",
      note: "Build a house plan room by room, capture facades in separate passes and mark up the plan.",
    },
    {
      icon: "⬡",
      title: "Edit with precision",
      note: "Use grid and snapping, edit vertices, edges and faces. Export for printing, games and CAD.",
    },
  ],
} as const;

export function Onboarding({ language }: { language: "ru" | "en" }) {
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
  const slide = slides[step];
  const last = step === slides.length - 1;
  const ru = language === "ru";

  return (
    <Modal
      visible={visible}
      animationType="fade"
      presentationStyle="fullScreen"
      onRequestClose={finish}
    >
      <SafeAreaView style={local.screen}>
        <View style={local.topBar}>
          <Text style={local.brand}>Physical AI 3D</Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={ru ? "Пропустить приветствие" : "Skip welcome"}
            hitSlop={12}
            onPress={finish}
          >
            <Text style={local.skip}>{ru ? "Пропустить" : "Skip"}</Text>
          </Pressable>
        </View>

        <View style={local.body} accessibilityViewIsModal>
          <View style={local.icon} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            <Text style={local.iconText}>{slide.icon}</Text>
          </View>
          <Text style={local.title}>{slide.title}</Text>
          <Text style={local.note}>{slide.note}</Text>
        </View>

        <View style={local.footer}>
          <View style={local.dots} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            {slides.map((_, index) => (
              <View key={index} style={[local.dot, index === step && local.dotActive]} />
            ))}
          </View>
          <Pressable
            accessibilityRole="button"
            style={[styles.button, styles.buttonPrimary, local.next]}
            onPress={() => (last ? finish() : setStep((current) => current + 1))}
          >
            <Text style={styles.buttonText}>
              {last ? (ru ? "Начать" : "Get started") : ru ? "Далее" : "Next"}
            </Text>
          </Pressable>
        </View>
      </SafeAreaView>
    </Modal>
  );
}

const local = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.bg,
    paddingHorizontal: 24,
  },
  topBar: {
    minHeight: 64,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  brand: {
    color: colors.text,
    fontSize: 15,
    fontWeight: "700",
  },
  skip: {
    color: colors.muted,
    fontSize: 14,
    fontWeight: "600",
    paddingVertical: 10,
  },
  body: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "center",
    width: "100%",
    maxWidth: 520,
    gap: 18,
    paddingBottom: 16,
  },
  icon: {
    width: 88,
    height: 88,
    borderRadius: 24,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.panel2,
    borderColor: colors.border,
    borderWidth: 1,
    marginBottom: 10,
  },
  iconText: {
    color: colors.accent,
    fontSize: 42,
    lineHeight: 48,
  },
  title: {
    color: colors.text,
    fontSize: 28,
    lineHeight: 34,
    fontWeight: "700",
    textAlign: "center",
  },
  note: {
    color: colors.muted,
    fontSize: 16,
    lineHeight: 24,
    textAlign: "center",
  },
  footer: {
    alignSelf: "center",
    width: "100%",
    maxWidth: 520,
    gap: 20,
    paddingBottom: 16,
  },
  dots: {
    flexDirection: "row",
    justifyContent: "center",
    gap: 8,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.border,
  },
  dotActive: {
    width: 24,
    backgroundColor: colors.accent,
  },
  next: {
    minHeight: 48,
    justifyContent: "center",
  },
});
