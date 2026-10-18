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
import {
  Image,
  type ImageSourcePropType,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";

import { ArrowRightIcon, CubeIcon, ImportIcon, ScanIcon, SparklesIcon } from "@/src/AppIcons";
import { useIsTablet } from "@/src/layout";
import { SheetShell } from "@/src/SheetShell";
import { colors, elevationHigh, elevationLow, radii, styles } from "@/src/theme";

/** Static requires let Metro bundle every known illustration; unknown ids keep the fallback glyph. */
const SCENARIO_VISUALS: Partial<Record<string, ImageSourcePropType>> = {
  room_scan: require("../assets/scenarios/room_scan.png") as ImageSourcePropType,
  interior_structure: require("../assets/scenarios/interior_structure.png") as ImageSourcePropType,
  exterior_structure: require("../assets/scenarios/exterior_structure.png") as ImageSourcePropType,
  object_scan: require("../assets/scenarios/object_scan.png") as ImageSourcePropType,
  printable_object: require("../assets/scenarios/printable_object.png") as ImageSourcePropType,
  general_character: require("../assets/scenarios/general_character.png") as ImageSourcePropType,
  game_character: require("../assets/scenarios/game_character.png") as ImageSourcePropType,
  game_environment: require("../assets/scenarios/game_environment.png") as ImageSourcePropType,
  house_design: require("../assets/scenarios/house_design.png") as ImageSourcePropType,
  machine_part: require("../assets/scenarios/machine_part.png") as ImageSourcePropType,
  dimensioned_part: require("../assets/scenarios/dimensioned_part.png") as ImageSourcePropType,
  floor_plan: require("../assets/scenarios/floor_plan.png") as ImageSourcePropType,
  import_file: require("../assets/scenarios/import_file.png") as ImageSourcePropType,
};

function GroupIcon({ group }: { group: string }) {
  const props = { color: colors.accent, size: 19, strokeWidth: 1.8 };
  if (group === "scan") return <ScanIcon {...props} />;
  if (group === "generate") return <SparklesIcon {...props} />;
  if (group === "model") return <CubeIcon {...props} />;
  return <ImportIcon {...props} />;
}

function ScenarioArtwork({ scenario, size }: { scenario: CreateScenario; size: number }) {
  const source = SCENARIO_VISUALS[scenario.id];
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: radii.compact,
        overflow: "hidden",
        backgroundColor: colors.viewport,
        borderColor: colors.border,
        borderWidth: 1,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {source ? (
        <Image source={source} resizeMode="cover" style={{ width: "100%", height: "100%" }} />
      ) : (
        <Text style={{ color: colors.accent, fontSize: size * 0.38 }}>{scenario.icon}</Text>
      )}
    </View>
  );
}

function ScenarioArrow({ active }: { active: boolean }) {
  return (
    <View
      style={{
        width: 30,
        height: 30,
        borderRadius: radii.pill,
        borderColor: colors.accent,
        borderWidth: 1,
        backgroundColor: active ? colors.accentButton : colors.panel,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <ArrowRightIcon color={active ? "#fff" : colors.accent} size={16} strokeWidth={2.2} />
    </View>
  );
}

export function CreateSheet({
  visible,
  onClose,
  onChoose,
}: {
  visible: boolean;
  onClose: () => void;
  onChoose: (scenario: CreateScenario) => void;
}) {
  const isTablet = useIsTablet();
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
  const guideSteps = guide ? (
    <View
      style={[
        {
          backgroundColor: colors.accentWash,
          borderColor: colors.border,
          borderWidth: 1,
          borderRadius: radii.section,
          padding: 12,
          gap: 8,
          ...elevationLow,
        },
        isTablet && { width: 230, alignSelf: "stretch" },
      ]}
    >
      {guide.guide.map((item, index) => (
        <Pressable key={index} style={[styles.row, { gap: 10 }]} onPress={() => setStep(index)}>
          <View
            style={{
              width: 20,
              height: 20,
              borderRadius: radii.pill,
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
              flex: 1,
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
  ) : null;

  const guideDetail = guide && current ? (
    <View style={{ flex: 1, gap: 12 }}>
      <Text style={styles.sectionTitle}>{current.title.ru}</Text>
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
      <View style={[styles.row, isTablet && { marginTop: "auto" }]}>
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
    </View>
  ) : null;

  return (
    <SheetShell
      visible={visible}
      onClose={close}
      maxHeightPercent="86%"
      tabletWidth={760}
      phoneBackdropColor="rgba(0,0,0,0.55)"
      accessibilityLabel="Закрыть"
      contentGap={12}
    >
      <View style={[styles.row, { justifyContent: "space-between", alignItems: "flex-start" }]}>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={[styles.title, { fontSize: 26, lineHeight: 30 }]}>
            {guide ? `Создание: ${guide.title.ru}` : "Что вы хотите создать?"}
          </Text>
          {!guide && (
            <Text style={styles.sectionSubtitle}>Выберите способ, с которого начнём работу</Text>
          )}
        </View>
        <Pressable onPress={close} hitSlop={12} accessibilityLabel="Закрыть">
          <Text style={[styles.sectionTitle, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>

      {!guide || !current ? (
        <ScrollView contentContainerStyle={{ gap: isTablet ? 0 : 16 }}>
          {SCENARIO_GROUPS.map((group) => {
            // Mobile can start every goal plus the real file-import flow. Floor-plan import
            // stays hidden until a mobile route exists for its annotation workflow.
            const items = scenariosIn(group.id).filter(
              (scenario) => scenario.goal || scenario.id === "import_file",
            );
            if (items.length === 0) return null;
            return isTablet ? (
              <View
                key={group.id}
                style={{
                  flexDirection: "row",
                  gap: 28,
                  paddingVertical: 20,
                  borderTopWidth: 1,
                  borderTopColor: colors.border,
                }}
              >
                <View
                  style={{
                    width: 190,
                    gap: 5,
                    paddingLeft: 12,
                    borderLeftWidth: 2,
                    borderLeftColor: colors.accent,
                  }}
                >
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                    <GroupIcon group={group.id} />
                    <Text style={styles.sectionTitle}>{group.title.ru}</Text>
                  </View>
                  <Text style={styles.sectionSubtitle}>{group.note.ru}</Text>
                </View>
                <View style={{ flex: 1, gap: 10 }}>
                  {items.map((scenario) => (
                    <Pressable
                      key={scenario.id}
                      style={({ pressed }) => [
                        styles.card,
                        {
                          minHeight: 104,
                          borderRadius: radii.feature,
                          flexDirection: "row",
                          alignItems: "center",
                          gap: 12,
                          ...elevationLow,
                        },
                        pressed && {
                          ...elevationHigh,
                          borderColor: colors.accent,
                          shadowColor: colors.accent,
                          shadowOpacity: 0.42,
                        },
                      ]}
                      onPress={() => pick(scenario)}
                    >
                      {({ pressed }) => (
                        <>
                          <View style={{ flex: 1, gap: 4 }}>
                            <Text style={styles.heading}>
                              {scenario.title.ru}
                              {scenario.prefersLidar ? "  · LiDAR" : ""}
                            </Text>
                            <Text style={styles.sectionSubtitle}>{scenario.note.ru}</Text>
                          </View>
                          <ScenarioArtwork scenario={scenario} size={72} />
                          <ScenarioArrow active={pressed} />
                        </>
                      )}
                    </Pressable>
                  ))}
                </View>
              </View>
            ) : (
              <View key={group.id} style={{ gap: 10 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                  <GroupIcon group={group.id} />
                  <View style={styles.sectionHeader}>
                    <Text style={styles.sectionTitle}>{group.title.ru}</Text>
                    <Text style={styles.sectionSubtitle}>{group.note.ru}</Text>
                  </View>
                </View>
                {items.map((scenario) => (
                  <Pressable
                    key={scenario.id}
                    style={({ pressed }) => [
                      styles.card,
                      {
                        minHeight: 116,
                        backgroundColor: colors.panel2,
                        borderRadius: radii.feature,
                        flexDirection: "row",
                        alignItems: "center",
                        gap: 10,
                        ...elevationLow,
                      },
                      pressed && {
                        ...elevationHigh,
                        borderColor: colors.accent,
                        shadowColor: colors.accent,
                        shadowOpacity: 0.42,
                      },
                    ]}
                    onPress={() => pick(scenario)}
                  >
                    {({ pressed }) => (
                      <>
                        <View style={{ flex: 1, gap: 4 }}>
                          <Text style={[styles.heading, { lineHeight: 19 }]}>
                            {scenario.title.ru}
                            {scenario.prefersLidar ? "  · LiDAR" : ""}
                          </Text>
                          <Text style={styles.sectionSubtitle}>{scenario.note.ru}</Text>
                        </View>
                        <ScenarioArtwork scenario={scenario} size={80} />
                        <ScenarioArrow active={pressed} />
                      </>
                    )}
                  </Pressable>
                ))}
              </View>
            );
          })}
        </ScrollView>
      ) : (
        <ScrollView contentContainerStyle={{ gap: 12 }}>
          {isTablet ? (
            <View style={{ flexDirection: "row", gap: 24, minHeight: 260 }}>
              {guideSteps}
              {guideDetail}
            </View>
          ) : (
            <>
              {guideSteps}
              {guideDetail}
            </>
          )}
        </ScrollView>
      )}
    </SheetShell>
  );
}
