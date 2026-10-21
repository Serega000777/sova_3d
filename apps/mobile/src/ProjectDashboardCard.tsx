import { relativeTime } from "@physical-ai/contracts";
import { Pressable, Text, View } from "react-native";

import { projectDashboardState, type ProjectCheckState } from "./project-dashboard";
import { colors, styles } from "./theme";

interface ProjectDashboardCardProps {
  hasModel: boolean;
  versionCount: number;
  updatedAt: string | null;
  checkState: ProjectCheckState;
  onCheck: () => void;
  onComments: () => void;
  onVersions: () => void;
  onExport: () => void;
}

export function ProjectDashboardCard({
  hasModel,
  versionCount,
  updatedAt,
  checkState,
  onCheck,
  onComments,
  onVersions,
  onExport,
}: ProjectDashboardCardProps) {
  const summary = projectDashboardState({ hasModel, versionCount, checkState });
  const checkColor =
    checkState === "passed" ? colors.green : checkState === "failed" ? colors.red : colors.yellow;

  return (
    <View style={[styles.card, { gap: 12 }]} accessibilityLabel="Панель проекта">
      <View style={{ gap: 4 }}>
        <Text style={styles.heading}>Панель проекта</Text>
        <Text style={styles.muted}>
          Только подтверждённые данные проекта — без расчётного процента готовности.
        </Text>
      </View>
      <View style={[styles.row, { flexWrap: "wrap" }]}>
        <View style={[styles.statusBadge, { backgroundColor: hasModel ? colors.greenWash : colors.yellowWash }]}>
          <View style={[styles.statusDot, { backgroundColor: hasModel ? colors.green : colors.yellow }]} />
          <Text style={[styles.statusText, { color: hasModel ? colors.green : colors.yellow }]}>{summary.modelLabel}</Text>
        </View>
        <View style={[styles.statusBadge, { backgroundColor: colors.panel2 }]}>
          <Text style={styles.statusText}>{summary.versionLabel}</Text>
        </View>
      </View>
      <Text style={[styles.sectionSubtitle, { color: checkColor }]}>{summary.checkLabel}</Text>
      <Text style={styles.sectionSubtitle}>
        Сервер обновлён: {updatedAt ? relativeTime(updatedAt, Date.now(), "ru") : "нет данных"}
      </Text>
      <View style={{ gap: 8 }}>
        <Text style={styles.heading}>Следующие действия</Text>
        <View style={[styles.row, { flexWrap: "wrap" }]}>
          <Pressable style={styles.button} onPress={onCheck}>
            <Text style={styles.buttonText}>Проверить модель</Text>
          </Pressable>
          <Pressable style={styles.button} onPress={onComments}>
            <Text style={styles.buttonText}>Комментарии</Text>
          </Pressable>
          <Pressable style={styles.button} onPress={onVersions}>
            <Text style={styles.buttonText}>Версии</Text>
          </Pressable>
          <Pressable style={[styles.button, styles.buttonPrimary]} onPress={onExport}>
            <Text style={styles.buttonText}>Подготовить экспорт</Text>
          </Pressable>
        </View>
      </View>
    </View>
  );
}
