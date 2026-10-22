import { relativeTime, type Project } from "@physical-ai/contracts";
import { Redirect, useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useIsTablet } from "@/src/layout";
import { buildProjectAnalytics } from "@/src/project-analytics";
import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

function Metric({ value, label, accent = colors.text }: { value: number; label: string; accent?: string }) {
  return (
    <View style={[styles.card, { flex: 1, minWidth: 140, gap: 4 }]}>
      <Text style={[styles.title, { color: accent, fontSize: 30 }]}>{value}</Text>
      <Text style={styles.sectionSubtitle}>{label}</Text>
    </View>
  );
}

export default function AnalyticsScreen() {
  const router = useRouter();
  const isTablet = useIsTablet();
  const { session, ready, client } = useSession();
  const [projects, setProjects] = useState<Project[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const analytics = useMemo(() => buildProjectAnalytics(projects, Date.now()), [projects]);
  const peak = Math.max(1, ...analytics.activity.map((item) => item.updatedProjects));

  const refresh = useCallback(async () => {
    if (!client || !session) return;
    setRefreshing(true);
    try {
      setProjects(await client.listProjects(session.workspaceId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoaded(true);
      setRefreshing(false);
    }
  }, [client, session]);

  useFocusEffect(
    useCallback(() => {
      void refresh();
    }, [refresh]),
  );

  if (!ready) return <View style={styles.screen} />;
  if (!session) return <Redirect href="/sign-in" />;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={["top", "bottom"]}>
      <ScrollView
        style={styles.screen}
        contentContainerStyle={[
          styles.content,
          { paddingBottom: 40 },
          isTablet && { width: "100%", maxWidth: 960, alignSelf: "center", paddingHorizontal: 28 },
        ]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.muted} />}
      >
        <View style={[styles.row, { justifyContent: "space-between" }]}>
          <Pressable accessibilityRole="button" onPress={() => router.back()} style={styles.button}>
            <Text style={styles.buttonText}>← Проекты</Text>
          </Pressable>
          <Text style={styles.muted}>30 дней</Text>
        </View>

        <View style={{ gap: 4 }}>
          <Text style={[styles.title, { fontSize: 30 }]}>Аналитика проектов</Text>
          <Text style={styles.muted}>Статистика из текущего списка проектов рабочего пространства.</Text>
        </View>

        {error ? <Text style={[styles.sectionSubtitle, { color: colors.red }]}>{error}</Text> : null}
        {!loaded && refreshing ? <Text style={styles.muted}>Загружаем статистику…</Text> : null}

        <View style={[styles.row, { flexWrap: "wrap", alignItems: "stretch" }]}>
          <Metric value={analytics.totalProjects} label="всего проектов" accent={colors.accent} />
          <Metric value={analytics.modelsCreated} label="с текущей моделью" accent={colors.green} />
          <Metric value={analytics.drafts} label="черновиков без модели" accent={colors.yellow} />
          <Metric value={analytics.updatedInWindow} label="обновлялись за 30 дней" />
        </View>

        <View style={[styles.card, { gap: 14 }]}>
          <View style={{ gap: 4 }}>
            <Text style={styles.heading}>Активность за 30 дней</Text>
            <Text style={styles.muted}>Число проектов по дате их последнего серверного обновления.</Text>
          </View>
          <View style={{ height: 132, flexDirection: "row", alignItems: "flex-end", gap: 3 }} accessibilityLabel="График обновлений проектов за 30 дней">
            {analytics.activity.map((item) => (
              <View key={item.day} style={{ flex: 1, minWidth: 2, alignItems: "stretch", justifyContent: "flex-end" }}>
                <View
                  accessibilityLabel={`${item.day}: ${item.updatedProjects}`}
                  style={{
                    height: item.updatedProjects === 0 ? 2 : Math.max(10, (item.updatedProjects / peak) * 124),
                    borderRadius: 3,
                    backgroundColor: item.updatedProjects === 0 ? colors.border : colors.accent,
                  }}
                />
              </View>
            ))}
          </View>
          <Text style={styles.sectionSubtitle}>Это активность проектов, а не число созданных версий или моделей.</Text>
        </View>

        {analytics.mostRecent ? (
          <Pressable
            accessibilityRole="button"
            style={[styles.card, { gap: 8 }]}
            onPress={() => router.push(`/project/${analytics.mostRecent?.id}`)}
          >
            <Text style={styles.heading}>Последний активный проект</Text>
            <Text style={styles.title}>{analytics.mostRecent.name}</Text>
            <Text style={styles.muted}>
              Обновлён {relativeTime(analytics.mostRecent.updated_at, Date.now(), "ru")}
            </Text>
            <Text style={[styles.buttonText, { color: colors.accent }]}>Открыть проект →</Text>
          </Pressable>
        ) : loaded && !error ? (
          <View style={styles.card}>
            <Text style={styles.heading}>Пока нет проектов</Text>
            <Text style={styles.muted}>Создайте первый проект — здесь появится измеримая активность.</Text>
          </View>
        ) : null}

        <View style={[styles.card, { gap: 6, borderColor: colors.yellow }]}>
          <Text style={styles.heading}>Граница данных</Text>
          <Text style={styles.muted}>
            API пока не хранит статус «завершён» и не выдаёт агрегат проверок по рабочему пространству.
            Поэтому экран не показывает выдуманный процент готовности или успешных проверок.
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
