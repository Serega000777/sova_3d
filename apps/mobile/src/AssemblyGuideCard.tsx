import { Pressable, Text, View } from "react-native";

import type { MechanismAssemblyGuide } from "./mechanism-assembly-guide";
import { colors, radii, styles } from "./theme";

export function AssemblyGuideCard({
  guide,
  language,
  nodeNames,
  onSelectNode,
}: {
  guide: MechanismAssemblyGuide;
  language: "ru" | "en";
  nodeNames: ReadonlyMap<string, string>;
  onSelectNode: (nodeId: string) => void;
}) {
  const ru = language === "ru";
  return (
    <View
      style={styles.card}
      accessibilityLabel={ru ? "Инструкция по сборке этой версии" : "Assembly guide for this version"}
    >
      <Text style={styles.heading}>
        {ru ? "Инструкция по сборке этой версии" : "Assembly guide for this version"}
      </Text>
      <Text style={styles.muted}>
        {ru
          ? "Шаги построены только по сохранённым деталям механизма. Нажмите деталь, чтобы выделить её в сцене."
          : "Steps use only the mechanism parts saved in this version. Press a part to select it in the scene."}
      </Text>
      {guide.steps.map((step, index) => (
        <View
          key={step.id}
          style={{ gap: 7, paddingTop: 12, borderTopWidth: index === 0 ? 0 : 1, borderTopColor: colors.border }}
        >
          <Text style={styles.heading}>
            {index + 1}. {ru ? step.titleRu : step.titleEn}
          </Text>
          <Text style={styles.text}>{ru ? step.detailRu : step.detailEn}</Text>
          <View
            style={{ flexDirection: "row", flexWrap: "wrap", gap: 7 }}
            accessibilityLabel={ru ? "Детали сцены" : "Scene parts"}
          >
            {step.nodeIds.map((nodeId) => (
              <Pressable
                key={nodeId}
                style={[styles.chip, { borderRadius: radii.pill }]}
                onPress={() => onSelectNode(nodeId)}
              >
                <Text style={styles.chipText}>{nodeNames.get(nodeId) ?? nodeId}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      ))}
      <Text style={[styles.muted, { color: colors.yellow }]}>
        {ru
          ? "Фотографии, внешний крепёж и отметки выполнения не добавлены. Реальную посадку и прочность проверьте физически."
          : "Photos, external fasteners and completion tracking are not included. Validate real fit and strength physically."}
      </Text>
    </View>
  );
}
