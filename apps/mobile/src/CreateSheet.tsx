/**
 * The Create sheet (F-084): ready scenarios grouped by what the person wants to do, from the
 * shared registry. A scan scenario shows its preparation guide before capture starts.
 */
import {
  type CreateScenario,
  SCENARIO_GROUPS,
  getProjectGoal,
  scenariosIn,
} from "@physical-ai/contracts";
import { useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";

import { colors, styles } from "@/src/theme";

export function CreateSheet({
  visible,
  onClose,
  onChoose,
}: {
  visible: boolean;
  onClose: () => void;
  onChoose: (scenario: CreateScenario) => void;
}) {
  const [guide, setGuide] = useState<CreateScenario | null>(null);
  const [step, setStep] = useState(0);

  const close = () => {
    setGuide(null);
    setStep(0);
    onClose();
  };

  const pick = (scenario: CreateScenario) => {
    const scans = scenario.goal ? getProjectGoal(scenario.goal)?.source === "scan" : false;
    if (scans && scenario.guide.length > 0) {
      setGuide(scenario);
      setStep(0);
    } else {
      close();
      onChoose(scenario);
    }
  };

  const current = guide?.guide[step];
  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={close}>
      <View style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" }}>
        <Pressable style={{ flex: 1 }} onPress={close} accessibilityLabel="Закрыть" />
        <View
          style={{
            maxHeight: "86%",
            backgroundColor: colors.panel,
            borderTopLeftRadius: 22,
            borderTopRightRadius: 22,
            padding: 18,
            gap: 12,
          }}
        >
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <Text style={styles.title}>{guide ? `Создание: ${guide.title.ru}` : "Что вы хотите создать?"}</Text>
            <Pressable onPress={close} hitSlop={12} accessibilityLabel="Закрыть">
              <Text style={[styles.title, { color: colors.muted }]}>×</Text>
            </Pressable>
          </View>

          {!guide || !current ? (
            <ScrollView contentContainerStyle={{ gap: 16 }}>
              {SCENARIO_GROUPS.map((group) => {
                // the phone has no floor-plan or file-conversion screens: show what it can start
                const items = scenariosIn(group.id).filter((scenario) => scenario.goal);
                if (items.length === 0) return null;
                return (
                  <View key={group.id} style={{ gap: 8 }}>
                    <Text style={styles.heading}>
                      {group.title.ru} <Text style={styles.muted}>· {group.note.ru}</Text>
                    </Text>
                    {items.map((scenario) => (
                      <Pressable
                        key={scenario.id}
                        style={[styles.card, { backgroundColor: colors.panel2, flexDirection: "row", alignItems: "center", gap: 12 }]}
                        onPress={() => pick(scenario)}
                      >
                        <View
                          style={{ width: 40, height: 40, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(91,156,255,0.14)" }}
                        >
                          <Text style={{ color: colors.accent, fontSize: 20 }}>{scenario.icon}</Text>
                        </View>
                        <View style={{ flex: 1 }}>
                          <Text style={styles.heading}>
                            {scenario.title.ru}
                            {scenario.prefersLidar ? "  · LiDAR" : ""}
                          </Text>
                          <Text style={styles.muted}>{scenario.note.ru}</Text>
                        </View>
                      </Pressable>
                    ))}
                  </View>
                );
              })}
            </ScrollView>
          ) : (
            <ScrollView contentContainerStyle={{ gap: 12 }}>
              <View style={{ backgroundColor: "rgba(91,156,255,0.1)", borderRadius: 12, padding: 12, gap: 8 }}>
                {guide.guide.map((item, index) => (
                  <Pressable key={index} style={[styles.row, { gap: 10 }]} onPress={() => setStep(index)}>
                    <View
                      style={{
                        width: 20,
                        height: 20,
                        borderRadius: 10,
                        borderWidth: 2,
                        borderColor: colors.accent,
                        backgroundColor: index < step ? colors.accent : "transparent",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      {index < step && <Text style={{ color: "#fff", fontSize: 11 }}>✓</Text>}
                    </View>
                    <Text
                      style={{
                        color: index === step ? colors.accent : colors.muted,
                        fontWeight: index === step ? "700" : "400",
                        textDecorationLine: index < step ? "line-through" : "none",
                      }}
                    >
                      {item.title.ru}
                    </Text>
                  </Pressable>
                ))}
              </View>
              <Text style={styles.heading}>{current.title.ru}</Text>
              {current.tips.map((tip, index) => (
                <Text key={index} style={styles.text}>• {tip.ru}</Text>
              ))}
              {guide.limits && step === 1 && (
                <Text style={styles.muted}>
                  Нужно от {guide.limits.minFrames} до {guide.limits.maxFrames} кадров.
                </Text>
              )}
              {guide.prefersLidar && (
                <Text style={styles.muted}>
                  Точные размеры даёт LiDAR (iPhone/iPad Pro). Без него размер придётся указать вручную.
                </Text>
              )}
              <View style={styles.row}>
                {step > 0 && (
                  <Pressable style={styles.button} onPress={() => setStep(step - 1)}>
                    <Text style={styles.buttonText}>Назад</Text>
                  </Pressable>
                )}
                {step < guide.guide.length - 1 && (
                  <Pressable style={styles.button} onPress={() => setStep(step + 1)}>
                    <Text style={styles.buttonText}>Далее</Text>
                  </Pressable>
                )}
                <Pressable
                  style={[styles.button, styles.buttonPrimary, { flexGrow: 1 }]}
                  onPress={() => {
                    const chosen = guide;
                    close();
                    onChoose(chosen);
                  }}
                >
                  <Text style={styles.buttonText}>Начать съёмку</Text>
                </Pressable>
              </View>
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
}
