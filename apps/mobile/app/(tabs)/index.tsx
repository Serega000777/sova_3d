import { getScenario, libraryView, relativeTime, type Project } from "@physical-ai/contracts";
import { Link, useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState, type ReactNode } from "react";
import {
  Image,
  ImageBackground,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  ArrowRightIcon,
  CubeIcon,
  HousePlanIcon,
  ImportIcon,
  MoreIcon,
  Photo3dIcon,
  ScanIcon,
  SearchIcon,
  SparklesIcon,
} from "@/src/AppIcons";
import { useCreateFlow } from "@/src/CreateFlow";
import { useSession } from "@/src/session";
import { colors, elevationHigh, elevationLow, radii, styles } from "@/src/theme";

const heroImage = require("../../assets/auth/sova-villa-night.png");

function initials(name: string | null | undefined): string {
  const clean = name?.trim();
  if (!clean) return "S";
  const parts = clean.replace(/^@/, "").split(/[\s._-]+/).filter(Boolean);
  return parts.slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "S";
}

function SectionHeading({ title, action, onPress }: { title: string; action: string; onPress: () => void }) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <Pressable hitSlop={8} onPress={onPress} style={({ pressed }) => ({ opacity: pressed ? 0.6 : 1 })}>
        <Text style={{ color: colors.accent, fontSize: 13, fontWeight: "700" }}>{action}</Text>
      </Pressable>
    </View>
  );
}

type QuickCard = {
  title: string;
  note: string;
  icon: (color: string) => ReactNode;
  scenario?: string;
  openSheet?: boolean;
};

const QUICK_CARDS: QuickCard[] = [
  { title: "Дом и планировка", note: "Форма, размеры и этажи", icon: (color) => <HousePlanIcon color={color} />, scenario: "house_design" },
  { title: "3D по фото", note: "Модель по чертежу", icon: (color) => <Photo3dIcon color={color} />, scenario: "dimensioned_part" },
  { title: "Сканировать помещение", note: "Камера или LiDAR", icon: (color) => <ScanIcon color={color} />, scenario: "room_scan" },
  { title: "AI по описанию", note: "Идея в готовую модель", icon: (color) => <SparklesIcon color={color} />, scenario: "printable_object" },
  { title: "С нуля", note: "Выберите точный сценарий", icon: (color) => <CubeIcon color={color} />, openSheet: true },
  { title: "Импорт", note: "OBJ, FBX, GLB, STL", icon: (color) => <ImportIcon color={color} />, scenario: "import_file" },
];

export default function HomeScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const { session, client } = useSession();
  const { openCreate, chooseScenario } = useCreateFlow();
  const [projects, setProjects] = useState<Project[]>([]);
  const [thumbnailUrls, setThumbnailUrls] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [favoriteCount, setFavoriteCount] = useState<number | null>(null);
  const [purchaseCount, setPurchaseCount] = useState<number | null>(null);

  const visibleProjects = useMemo(
    () => libraryView(projects, { query, filter: "all", sort: "updated" }),
    [projects, query],
  );
  const recentProjects = useMemo(
    () => libraryView(projects, { query: "", filter: "all", sort: "updated" }),
    [projects],
  );
  const continueProject = recentProjects[0] ?? null;

  const refresh = useCallback(async () => {
    if (!client || !session) return;
    setRefreshing(true);
    try {
      const rows = await client.listProjects(session.workspaceId);
      setProjects(rows);
      const collections = await Promise.all([
        client.favoriteListings(),
        client.myOrders(),
      ]).catch(() => null);
      setFavoriteCount(collections?.[0].length ?? null);
      setPurchaseCount(collections?.[1].filter((order) => order.status === "completed").length ?? null);
      const previews = await Promise.all(
        rows.slice(0, 12).map(async (project) => {
          if (!project.head_version_id) return null;
          const url = await client.versionThumbnailUrl(project.head_version_id, project.thumbnail_asset_id).catch(() => null);
          return url ? ([project.id, url] as const) : null;
        }),
      );
      setThumbnailUrls(Object.fromEntries(previews.filter((entry): entry is readonly [string, string] => entry !== null)));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }, [client, session]);

  useFocusEffect(useCallback(() => { void refresh(); }, [refresh]));

  const runQuickCard = (card: QuickCard) => {
    if (card.openSheet) {
      openCreate();
      return;
    }
    const scenario = getScenario(card.scenario);
    if (scenario) chooseScenario(scenario);
  };

  const contentWidth = Math.min(width - 32, 960);
  const columns = contentWidth >= 720 ? 3 : 2;
  const quickWidth = (contentWidth - (columns - 1) * 10) / columns;
  const profileName = session?.displayName || session?.address;

  return (
    <SafeAreaView style={styles.screen} edges={["top"]}>
      <ScrollView
        style={styles.screen}
        contentContainerStyle={{ width: "100%", maxWidth: 992, alignSelf: "center", paddingHorizontal: 16, paddingTop: 10, paddingBottom: 28, gap: 24 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />}
      >
        <View style={{ gap: 14 }}>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 9 }}>
              <View style={{ width: 36, height: 36, borderRadius: 11, backgroundColor: colors.accentButton, alignItems: "center", justifyContent: "center", transform: [{ rotate: "-7deg" }] }}>
                <CubeIcon color="#fff" size={22} strokeWidth={2} />
              </View>
              <Text style={[styles.title, { fontSize: 22 }]}>Sova 3D</Text>
            </View>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 9 }}>
              <Pressable onPress={() => router.push("/profile")} accessibilityLabel="Открыть профиль" style={({ pressed }) => ({ width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.accentWashStrong, borderWidth: 1, borderColor: colors.accent, opacity: pressed ? 0.75 : 1 })}>
                <Text style={{ color: colors.text, fontSize: 13, fontWeight: "800" }}>{initials(profileName)}</Text>
              </Pressable>
            </View>
          </View>

          <View style={{ height: 46, borderRadius: radii.control, backgroundColor: colors.panel, borderWidth: 1, borderColor: query ? colors.accent : colors.border, flexDirection: "row", alignItems: "center", paddingHorizontal: 13, gap: 10 }}>
            <SearchIcon color={colors.muted} size={20} />
            <TextInput
              value={query}
              onChangeText={setQuery}
              placeholder="Поиск проектов"
              placeholderTextColor={colors.muted}
              clearButtonMode="while-editing"
              autoCorrect={false}
              style={{ flex: 1, color: colors.text, fontSize: 14, paddingVertical: 10 }}
            />
          </View>
        </View>

        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Создать новый проект"
          onPress={openCreate}
          style={({ pressed }) => ({ borderRadius: radii.hero, opacity: pressed ? 0.88 : 1, ...elevationHigh })}
        >
          <ImageBackground source={heroImage} imageStyle={{ borderRadius: radii.hero }} style={{ minHeight: 224, borderRadius: radii.hero, overflow: "hidden", justifyContent: "flex-end" }} resizeMode="cover">
            <View style={{ position: "absolute", top: 0, right: 0, bottom: 0, left: 0, backgroundColor: "rgba(5,7,8,0.46)", borderRadius: radii.hero }} />
            <View style={{ padding: 22, gap: 10 }}>
              <View style={{ alignSelf: "flex-start", backgroundColor: "rgba(255,107,26,0.92)", borderRadius: radii.pill, paddingHorizontal: 10, paddingVertical: 5 }}>
                <Text style={{ color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 0.4 }}>СОЗДАТЬ НОВОЕ</Text>
              </View>
              <Text style={[styles.title, { fontSize: 28, lineHeight: 31, maxWidth: 330 }]}>Преврати идею в точную 3D-модель</Text>
              <Text style={{ color: "rgba(255,255,255,0.84)", fontSize: 13, lineHeight: 18, maxWidth: 330 }}>По описанию, фотографии, скану или с нуля.</Text>
              <View style={{ alignSelf: "flex-start", marginTop: 3, minHeight: 38, paddingHorizontal: 14, borderRadius: radii.control, backgroundColor: colors.accentButton, flexDirection: "row", alignItems: "center", gap: 8 }}>
                <Text style={{ color: "#fff", fontWeight: "800" }}>Начать проект</Text>
                <ArrowRightIcon color="#fff" size={17} />
              </View>
            </View>
          </ImageBackground>
        </Pressable>

        <View style={{ gap: 12 }}>
          <SectionHeading title="Быстрый старт" action="Все инструменты" onPress={openCreate} />
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10 }}>
            {QUICK_CARDS.map((card) => (
              <Pressable
                key={card.title}
                accessibilityRole="button"
                onPress={() => runQuickCard(card)}
                style={({ pressed }) => ({
                  width: quickWidth,
                  minHeight: 148,
                  padding: 14,
                  gap: 10,
                  borderRadius: radii.feature,
                  borderWidth: 1,
                  borderColor: colors.border,
                  backgroundColor: colors.panel,
                  opacity: pressed ? 0.78 : 1,
                  ...elevationLow,
                })}
              >
                <View style={{ width: 40, height: 40, borderRadius: 12, backgroundColor: colors.accentWashStrong, alignItems: "center", justifyContent: "center" }}>
                  {card.icon(colors.accent)}
                </View>
                <View style={{ flex: 1, gap: 4 }}>
                  <Text style={[styles.heading, { lineHeight: 19 }]} numberOfLines={2}>{card.title}</Text>
                  <Text style={styles.sectionSubtitle} numberOfLines={2}>{card.note}</Text>
                </View>
                <ArrowRightIcon color={colors.muted} size={17} />
              </Pressable>
            ))}
          </View>
        </View>

        <View style={{ gap: 12 }}>
          <SectionHeading title="Моя библиотека" action="Открыть" onPress={() => router.push("/collections")} />
          <Pressable
            accessibilityRole="button"
            onPress={() => router.push("/collections")}
            style={({ pressed }) => [styles.card, { flexDirection: "row", gap: 12, opacity: pressed ? 0.78 : 1 }]}
          >
            <View style={{ flex: 1, gap: 4 }}>
              <Text style={styles.heading}>♥ Избранное</Text>
              <Text style={styles.sectionSubtitle}>{favoriteCount === null ? "Недоступно" : `${favoriteCount} сохранено`}</Text>
            </View>
            <View style={{ flex: 1, gap: 4 }}>
              <Text style={styles.heading}>↓ Загрузки</Text>
              <Text style={styles.sectionSubtitle}>{purchaseCount === null ? "Недоступно" : `${purchaseCount} покупок`}</Text>
            </View>
            <ArrowRightIcon color={colors.accent} size={20} />
          </Pressable>
        </View>

        {continueProject ? (
          <View style={{ gap: 12 }}>
            <SectionHeading title="Продолжить работу" action="Все проекты" onPress={() => router.push("/projects")} />
            <Link href={`/project/${continueProject.id}`} asChild>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Продолжить проект ${continueProject.name}`}
                style={({ pressed }) => ({
                  minHeight: 112,
                  borderRadius: radii.feature,
                  borderWidth: 1,
                  borderColor: colors.border,
                  backgroundColor: colors.panel,
                  overflow: "hidden",
                  flexDirection: "row",
                  opacity: pressed ? 0.8 : 1,
                  ...elevationLow,
                })}
              >
                {thumbnailUrls[continueProject.id] ? (
                  <Image
                    source={{ uri: thumbnailUrls[continueProject.id] }}
                    accessibilityLabel={`Превью проекта ${continueProject.name}`}
                    style={{ width: 112, minHeight: 112, backgroundColor: colors.viewport }}
                  />
                ) : (
                  <View style={{ width: 112, minHeight: 112, backgroundColor: colors.viewport, alignItems: "center", justifyContent: "center" }}>
                    <CubeIcon color={colors.muted} size={38} strokeWidth={1.2} />
                  </View>
                )}
                <View style={{ flex: 1, padding: 15, gap: 6, justifyContent: "center" }}>
                  <Text style={styles.heading} numberOfLines={1}>{continueProject.name}</Text>
                  <Text style={styles.sectionSubtitle}>
                    {continueProject.head_version_id ? "Последняя сохранённая модель" : "Черновик без модели"}
                  </Text>
                  <Text style={styles.sectionSubtitle}>
                    Изменён {relativeTime(continueProject.updated_at ?? continueProject.created_at, Date.now(), "ru")}
                  </Text>
                </View>
                <View style={{ alignSelf: "center", paddingRight: 16 }}>
                  <ArrowRightIcon color={colors.accent} size={20} />
                </View>
              </Pressable>
            </Link>
          </View>
        ) : null}

        <View style={{ gap: 12 }}>
          <SectionHeading title={query ? "Найденные проекты" : "Последние проекты"} action="Все проекты" onPress={() => router.push("/projects")} />
          {visibleProjects.length > 0 ? (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 11, paddingBottom: 5 }}>
              {visibleProjects.slice(0, 8).map((project) => (
                <Link key={project.id} href={`/project/${project.id}`} asChild>
                  <Pressable style={({ pressed }) => ({ width: Math.min(264, width * 0.72), borderRadius: radii.feature, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.panel, overflow: "hidden", opacity: pressed ? 0.82 : 1, ...elevationLow })}>
                    {thumbnailUrls[project.id] ? (
                      <Image source={{ uri: thumbnailUrls[project.id] }} accessibilityLabel={`Превью проекта ${project.name}`} style={{ width: "100%", height: 134, backgroundColor: colors.viewport }} />
                    ) : (
                      <View style={{ width: "100%", height: 134, backgroundColor: colors.viewport, alignItems: "center", justifyContent: "center" }}>
                        <CubeIcon color={colors.muted} size={38} strokeWidth={1.2} />
                      </View>
                    )}
                    <View style={{ padding: 13, flexDirection: "row", alignItems: "flex-start", gap: 8 }}>
                      <View style={{ flex: 1, gap: 4 }}>
                        <Text style={styles.heading} numberOfLines={1}>{project.name}</Text>
                        <Text style={styles.sectionSubtitle}>{relativeTime(project.updated_at ?? project.created_at, Date.now(), "ru")}</Text>
                      </View>
                      <View accessibilityLabel="Дополнительные действия" style={{ paddingTop: 1 }}><MoreIcon color={colors.muted} size={18} /></View>
                    </View>
                  </Pressable>
                </Link>
              ))}
            </ScrollView>
          ) : (
            <Pressable onPress={query ? () => setQuery("") : openCreate} style={({ pressed }) => ({ minHeight: 104, borderRadius: radii.section, borderWidth: 1, borderColor: colors.border, borderStyle: "dashed", backgroundColor: colors.panel, alignItems: "center", justifyContent: "center", gap: 6, opacity: pressed ? 0.7 : 1 })}>
              <Text style={styles.heading}>{query ? "Проекты не найдены" : "Здесь появятся ваши проекты"}</Text>
              <Text style={styles.sectionSubtitle}>{query ? "Сбросить поиск" : "Нажмите, чтобы создать первый"}</Text>
            </Pressable>
          )}
        </View>

        {error && <Text style={styles.error}>{error}</Text>}
      </ScrollView>
    </SafeAreaView>
  );
}
