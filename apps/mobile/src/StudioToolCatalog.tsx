import { Modal, Pressable, ScrollView, Text, View } from "react-native";

import {
  studioCatalogActions,
  type StudioCatalogAction,
} from "./studio-tool-catalog";
import { colors, elevationHigh, radii, styles } from "./theme";

const GROUPS = ["edit", "organize", "review"] as const;
const GROUP_LABELS = {
  edit: { ru: "Редактирование", en: "Edit" },
  organize: { ru: "Организация", en: "Organize" },
  review: { ru: "Проверка и вывод", en: "Review and output" },
};

export function StudioToolCatalog({
  visible,
  language,
  modelAvailable,
  activeAvailable,
  onClose,
  onAction,
}: {
  visible: boolean;
  language: "ru" | "en";
  modelAvailable: boolean;
  activeAvailable: boolean;
  onClose: () => void;
  onAction: (action: StudioCatalogAction) => void;
}) {
  const actions = studioCatalogActions({ modelAvailable, activeAvailable });
  const ru = language === "ru";
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View accessibilityViewIsModal style={{ flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.55)" }}>
        <View style={{ maxHeight: "88%", backgroundColor: colors.panel, borderTopLeftRadius: radii.hero, borderTopRightRadius: radii.hero, ...elevationHigh }}>
          <ScrollView contentContainerStyle={{ padding: 18, gap: 16 }}>
            <View style={{ gap: 4 }}>
              <Text accessibilityRole="header" style={styles.title}>{ru ? "Инструменты Studio" : "Studio tools"}</Text>
              <Text style={styles.muted}>
                {ru
                  ? "Единый каталог открывает существующие рабочие панели. Задание не запускается, пока вы явно не примените действие внутри инструмента."
                  : "This catalogue opens existing workspace panels. No job starts until you explicitly apply an action inside a tool."}
              </Text>
            </View>
            {GROUPS.map((group) => (
              <View key={group} style={{ gap: 8 }}>
                <Text style={styles.heading}>{GROUP_LABELS[group][language]}</Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                  {actions.filter((action) => action.group === group).map((action) => (
                    <Pressable
                      key={action.id}
                      accessibilityRole="button"
                      accessibilityLabel={action.label[language]}
                      accessibilityState={{ disabled: action.disabled }}
                      disabled={action.disabled}
                      onPress={() => onAction(action)}
                      style={[styles.button, { minWidth: 142, flexGrow: 1, flexBasis: "45%" }, action.disabled && { opacity: 0.38 }]}
                    >
                      <Text style={styles.buttonText}>{action.label[language]}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            ))}
            {!activeAvailable ? (
              <Text style={styles.muted}>
                {ru ? "Создайте или откройте версию модели, чтобы включить инструменты." : "Create or open a model version to enable tools."}
              </Text>
            ) : null}
            <Pressable accessibilityRole="button" style={styles.button} onPress={onClose}>
              <Text style={styles.buttonText}>{ru ? "Закрыть" : "Close"}</Text>
            </Pressable>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}
