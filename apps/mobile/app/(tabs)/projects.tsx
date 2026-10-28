import {
  getProjectGoal,
  isDraft,
  libraryView,
  relativeTime,
  type LibraryFilter,
  type Project,
  type ProjectGoalId,
  type Template,
} from "@physical-ai/contracts";
import { Link, Redirect, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Image, Pressable, RefreshControl, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useCreateFlow } from "@/src/CreateFlow";
import { AnalyticsIcon, ArrowRightIcon, CharacterIcon, CubeIcon, DrawingIcon, GameIcon, HousePlanIcon, LayersIcon, MechanicalIcon, PhoneStandIcon, PlusIcon, ScanIcon } from "@/src/AppIcons";
import { HouseTextCreator } from "@/src/HouseTextCreator";
import { useIsTablet } from "@/src/layout";
import { templateVisual } from "@/src/projects-screen";
import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

function SectionHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <Text style={styles.sectionSubtitle}>{subtitle}</Text>
    </View>
  );
}

function ProjectStatus({ draft }: { draft: boolean }) {
  const color = draft ? colors.yellow : colors.green;
  const backgroundColor = draft ? colors.yellowWash : colors.greenWash;
  return (
    <View style={[styles.statusBadge, { backgroundColor }]}>
      <View style={[styles.statusDot, { backgroundColor: color }]} />
      <Text style={[styles.statusText, { color }]}>{draft ? "Черновик" : "Есть модель"}</Text>
    </View>
  );
}

function GoalIcon({ id, size = 24 }: { id: ProjectGoalId; size?: number }) {
  const props = { color: colors.text, size };
  if (id === "general_character") return <CharacterIcon {...props} />;
  if (id === "game_character") return <GameIcon {...props} />;
  if (id === "game_environment") return <LayersIcon {...props} />;
  if (id === "house_design" || id === "interior_structure" || id === "exterior_structure") return <HousePlanIcon {...props} />;
  if (id === "machine_part") return <MechanicalIcon {...props} />;
  if (id === "dimensioned_part") return <DrawingIcon {...props} />;
  if (id === "object_scan" || id === "room_scan") return <ScanIcon {...props} />;
  return <CubeIcon {...props} />;
}

function TemplateIcon({ id, category }: { id: string; category: string }) {
  const props = { color: colors.text, size: 34, strokeWidth: 1.5 };
  if (id === "phone-stand") return <PhoneStandIcon {...props} />;
  if (id === "pipe-holder" || category === "workshop") return <MechanicalIcon {...props} />;
  if (id === "organizer" || id === "battery-tray") return <LayersIcon {...props} />;
  return <CubeIcon {...props} />;
}

export default function Projects() {
  const { session, ready } = useSession();
  if (!ready) return <View style={styles.screen} />;
  if (!session) return <Redirect href="/sign-in" />;

  return (
    <ProjectsHome />
  );
}

function ProjectsHome() {
  const router = useRouter();
  const { openCreate } = useCreateFlow();
  const { goal: requestedGoal, create: createRequest } = useLocalSearchParams<{
    goal?: string;
    create?: string;
  }>();
  const isTablet = useIsTablet();
  const { session, ready, client } = useSession();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [thumbnailUrls, setThumbnailUrls] = useState<Record<string, string>>({});
  const [templates, setTemplates] = useState<Template[]>([]);
  const [starting, setStarting] = useState<string | null>(null);
  const [goalId, setGoalId] = useState<ProjectGoalId | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<LibraryFilter>("all");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [houseMode, setHouseMode] = useState<"text" | "blank">("text");
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const goal = getProjectGoal(goalId);
  const visible = useMemo(
    () => (projects ? libraryView(projects, { query, filter, sort: "updated" }) : []),
    [projects, query, filter],
  );

  /** T-231: scan goals enter capture; creation goals get reversible smart defaults. */
  function chooseGoal(id: ProjectGoalId) {
    const chosen = getProjectGoal(id);
    if (!chosen) return;
    if (chosen.source === "scan" && chosen.scanSubject) {
      router.push(`/scan?subject=${chosen.scanSubject}`);
      return;
    }
    setGoalId(id);
    setName(chosen.defaultName.ru);
    setHouseMode("text");
    setError(null);
  }

  useEffect(() => {
    const requested = getProjectGoal(requestedGoal);
    if (requested && requested.source !== "scan") chooseGoal(requested.id);
    // `createRequest` makes selecting the same scenario twice reopen its form.
  }, [requestedGoal, createRequest]);

  async function createFromGoal() {
    if (!client || !session || !goal || !name.trim() || creating) return;
    setCreating(true);
    setError(null);
    try {
      const project = await client.createProject({
        workspace_id: session.workspaceId,
        name: name.trim(),
        description: goal.defaultPrompt.ru.trim() || null,
      });
      router.push(`/project/${project.id}?goal=${goal.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setCreating(false);
    }
  }

  const refresh = useCallback(async () => {
    if (!client || !session) return;
    setRefreshing(true);
    try {
      const rows = await client.listProjects(session.workspaceId);
      setProjects(rows);
      void Promise.all(
        rows.map(async (project, index) => {
          if (!project.head_version_id) return null;
          // Existing previews are cheap signed-URL lookups. Bound legacy backfills so opening
          // a large library cannot enqueue hundreds of render jobs at once.
          if (!project.thumbnail_asset_id && index >= 12) return null;
          const url = await client
            .versionThumbnailUrl(project.head_version_id, project.thumbnail_asset_id)
            .catch(() => null);
          return url ? ([project.id, url] as const) : null;
        }),
      ).then((entries) =>
        setThumbnailUrls(
          Object.fromEntries(entries.filter((entry): entry is readonly [string, string] => entry !== null)),
        ),
      );
      setTemplates(await client.listTemplates());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }, [client, session]);

  // Re-read on focus so a version made on the desktop shows up when you come back (T-089).
  useFocusEffect(
    useCallback(() => {
      void refresh();
    }, [refresh]),
  );

  /** F-070: a template is a project whose first version is already being built. */
  async function startTemplate(template: Template) {
    if (!client || !session) return;
    setStarting(template.id);
    setError(null);
    try {
      const started = await client.startFromTemplate({
        workspace_id: session.workspaceId,
        template_id: template.id,
        language: "ru",
      });
      const job = await client.waitForJob(started.job.job_id);
      if (job.status === "failed") {
        throw new Error((job.error as { message?: string } | null)?.message ?? "did not build");
      }
      router.push(`/project/${started.project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(null);
    }
  }

  if (!ready) return <View style={styles.screen} />;

  if (!session) {
    return (
      <View style={[styles.screen, styles.content]}>
        <View style={styles.card}>
          <Text style={styles.heading}>Физический ИИ 3D</Text>
          <Text style={styles.muted}>
            Опишите предмет — получите модель, которую можно редактировать и печатать. Войдите,
            чтобы начать.
          </Text>
          <Pressable
            style={[styles.button, styles.buttonPrimary]}
            onPress={() => router.push("/sign-in")}
          >
            <Text style={styles.buttonText}>Войти</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={["top"]}>
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[
        styles.content,
        { paddingBottom: 96 },
        isTablet && {
          width: "100%",
          maxWidth: 960,
          alignSelf: "center",
          paddingHorizontal: 28,
          gap: 16,
        },
      ]}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.muted} />
      }
    >
      <View style={[styles.row, { justifyContent: "space-between", alignItems: "flex-start", paddingVertical: 4 }]}>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={[styles.title, { fontSize: 29 }]}>Проекты</Text>
          <Text style={styles.muted}>Ваши модели, шаблоны и незавершённые идеи.</Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Открыть аналитику проектов"
          style={styles.button}
          onPress={() => router.push("/analytics")}
        >
          <AnalyticsIcon color={colors.text} size={17} />
          <Text style={styles.buttonText}>Аналитика</Text>
        </Pressable>
      </View>
      {!goal ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Создать проект"
          style={({ pressed }) => [styles.createHero, pressed && { opacity: 0.88 }]}
          onPress={openCreate}
        >
          <View style={styles.createHeroIcon}>
            <PlusIcon color={colors.text} size={31} strokeWidth={1.7} />
          </View>
          <View style={{ flex: 1, gap: 5 }}>
            <Text style={[styles.title, { fontSize: 25 }]}>Создать проект</Text>
            <Text style={[styles.text, { opacity: 0.9, lineHeight: 19 }]}>
              Скан, AI-модель или точная деталь — выберите готовый сценарий.
            </Text>
          </View>
          <ArrowRightIcon color={colors.text} size={22} />
        </Pressable>
      ) : (
        <View style={styles.card}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
            <GoalIcon id={goal.id} size={25} />
            <Text style={styles.title}>{goal.title.ru}</Text>
          </View>
          <Text style={styles.muted}>{goal.note.ru}</Text>
          {goal.id === "house_design" ? (
            <View style={styles.row}>
              <Pressable
                style={[
                  styles.chip,
                  houseMode === "text" && {
                    borderColor: colors.accent,
                    backgroundColor: colors.accentWash,
                  },
                ]}
                disabled={creating}
                onPress={() => setHouseMode("text")}
              >
                <Text style={styles.chipText}>По описанию</Text>
              </Pressable>
              <Pressable
                style={[
                  styles.chip,
                  houseMode === "blank" && {
                    borderColor: colors.accent,
                    backgroundColor: colors.accentWash,
                  },
                ]}
                disabled={creating}
                onPress={() => setHouseMode("blank")}
              >
                <Text style={styles.chipText}>Пустой проект</Text>
              </Pressable>
            </View>
          ) : null}
          {goal.id === "house_design" && houseMode === "text" && client ? (
            <HouseTextCreator
              client={client}
              workspaceId={session.workspaceId}
              onCreated={(projectId) => router.push(`/project/${projectId}?goal=house_design`)}
              onBack={() => {
                setGoalId(null);
                setName("");
              }}
            />
          ) : null}
          {goal.id !== "house_design" || houseMode === "blank" ? (
            <TextInput
              style={styles.input}
              value={name}
              onChangeText={setName}
              placeholder="Название проекта"
              placeholderTextColor={colors.muted}
            />
          ) : null}
          {goal.id !== "house_design" || houseMode === "blank" ? (
            <View style={styles.row}>
              <Pressable
                style={styles.button}
                disabled={creating}
                onPress={() => {
                  setGoalId(null);
                  setName("");
                }}
              >
                <Text style={styles.buttonText}>← Назад</Text>
              </Pressable>
              <Pressable
                style={[
                  styles.button,
                  styles.buttonPrimary,
                  (!name.trim() || creating) && { opacity: 0.5 },
                ]}
                disabled={!name.trim() || creating}
                onPress={() => void createFromGoal()}
              >
                <Text style={styles.buttonText}>
                  {creating ? "Создаём…" : "Открыть редактор →"}
                </Text>
              </Pressable>
            </View>
          ) : null}
        </View>
      )}

      {templates.length > 0 && (
        <View style={styles.featureSection}>
          <SectionHeader
            title="Начните с шаблона"
            subtitle="Готовые сценарии с проверенными параметрами."
          />
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ gap: 10, paddingHorizontal: 1, paddingBottom: 8 }}
          >
            {templates.map((template) => {
              const visual = templateVisual(template.id, template.category);
              const isStarting = starting === template.id;
              return (
                <Pressable
                  key={template.id}
                  accessibilityRole="button"
                  accessibilityLabel={template.title_ru}
                  style={({ pressed }) => [
                    styles.templateCard,
                    isStarting && { borderColor: colors.yellow },
                    pressed && { opacity: 0.82 },
                  ]}
                  disabled={starting !== null}
                  onPress={() => void startTemplate(template)}
                >
                  <View style={styles.templatePreview}>
                    <TemplateIcon id={template.id} category={template.category} />
                    <View style={[styles.statusBadge, { backgroundColor: colors.panel2 }]}>
                      <Text style={[styles.statusText, { color: colors.muted }]}>
                        {visual.categoryLabel}
                      </Text>
                    </View>
                  </View>
                  <View style={styles.templateBody}>
                    <View style={{ gap: 4 }}>
                      <Text style={styles.heading} numberOfLines={2}>{template.title_ru}</Text>
                      <Text style={styles.sectionSubtitle} numberOfLines={2}>
                        {template.description_ru}
                      </Text>
                    </View>
                    <Text style={[styles.statusText, { color: isStarting ? colors.yellow : colors.text }]}>
                      {isStarting ? "Строим…" : "Использовать →"}
                    </Text>
                  </View>
                </Pressable>
              );
            })}
          </ScrollView>
        </View>
      )}

      <Pressable
        accessibilityRole="button"
        style={({ pressed }) => [styles.scannerRow, pressed && { opacity: 0.8 }]}
        onPress={() => router.push("/scan")}
      >
        <View style={styles.scannerIcon}>
          <ScanIcon color={colors.text} size={22} />
        </View>
        <View style={{ flex: 1, gap: 3 }}>
          <Text style={styles.heading}>3D-сканер</Text>
          <Text style={styles.sectionSubtitle}>
            Предмет, интерьер или дом — выберите сценарий съёмки.
          </Text>
        </View>
        <ArrowRightIcon color={colors.muted} size={20} />
      </Pressable>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Открыть библиотеку компонентов"
        style={({ pressed }) => [styles.scannerRow, pressed && { opacity: 0.8 }]}
        onPress={() => router.push("/components")}
      >
        <View style={styles.scannerIcon}>
          <CubeIcon color={colors.text} size={22} />
        </View>
        <View style={{ flex: 1, gap: 3 }}>
          <Text style={styles.heading}>Компоненты</Text>
          <Text style={styles.sectionSubtitle}>
            Платы, датчики и механика с проверенными габаритами.
          </Text>
        </View>
        <ArrowRightIcon color={colors.muted} size={20} />
      </Pressable>

      {error && <Text style={styles.error}>{error}</Text>}

      {projects && projects.length > 0 && (isTablet ? (
        <View
          style={{
            flexDirection: "row",
            backgroundColor: colors.panel,
            borderColor: colors.border,
            borderWidth: 1,
            borderRadius: 18,
            overflow: "hidden",
          }}
        >
          <View style={{ width: 260, padding: 22, gap: 12, backgroundColor: colors.viewport }}>
            <Text style={[styles.title, { fontSize: 24 }]}>Библиотека</Text>
            <TextInput
              style={styles.input}
              value={query}
              onChangeText={setQuery}
              placeholder="Поиск по названию и описанию"
              placeholderTextColor={colors.muted}
              clearButtonMode="while-editing"
              autoCorrect={false}
            />
            <View style={styles.row}>
              {(
                [
                  ["all", "Все"],
                  ["models", "С моделью"],
                  ["drafts", "Черновики"],
                ] as const
              ).map(([id, label]) => (
                <Pressable
                  key={id}
                  style={[
                    styles.chip,
                    filter === id && { borderColor: colors.text, backgroundColor: colors.panel2 },
                  ]}
                  onPress={() => setFilter(id)}
                >
                  <Text style={styles.chipText}>{label}</Text>
                </Pressable>
              ))}
            </View>
          </View>
          <View style={{ flex: 1, padding: 18, flexDirection: "row", flexWrap: "wrap", alignContent: "flex-start", gap: 12 }}>
            {visible.map((project) => (
              <Link key={project.id} href={`/project/${project.id}`} asChild>
                <Pressable
                  style={{
                    width: "48%",
                    minWidth: 220,
                    flexGrow: 1,
                    overflow: "hidden",
                    borderWidth: 1,
                    borderColor: colors.border,
                    borderRadius: 14,
                    backgroundColor: colors.panel2,
                  }}
                >
                  {thumbnailUrls[project.id] ? (
                    <Image
                      source={{ uri: thumbnailUrls[project.id] }}
                      accessibilityLabel={`Превью проекта ${project.name}`}
                      style={{ width: "100%", height: 126, backgroundColor: colors.viewport }}
                    />
                  ) : (
                    <View style={{ width: "100%", height: 126, backgroundColor: colors.viewport, alignItems: "center", justifyContent: "center" }}>
                      <CubeIcon color={colors.muted} size={34} strokeWidth={1.3} />
                    </View>
                  )}
                  <View style={{ padding: 13, gap: 8 }}>
                    <Text style={[styles.heading, { fontSize: 16 }]} numberOfLines={2}>{project.name}</Text>
                    <View style={styles.row}>
                      <ProjectStatus draft={isDraft(project)} />
                      <Text style={styles.sectionSubtitle}>{relativeTime(project.updated_at ?? project.created_at, Date.now(), "ru")}</Text>
                    </View>
                  </View>
                </Pressable>
              </Link>
            ))}
            {visible.length === 0 && (
              <Text style={[styles.muted, { padding: 18 }]}>Ничего не найдено. Измените поиск или фильтр.</Text>
            )}
          </View>
        </View>
      ) : (
        <>
          <View style={{ gap: 8 }}>
            <Text style={styles.title}>Библиотека</Text>
            <TextInput
              style={styles.input}
              value={query}
              onChangeText={setQuery}
              placeholder="Поиск по названию и описанию"
              placeholderTextColor={colors.muted}
              clearButtonMode="while-editing"
              autoCorrect={false}
            />
            <View style={styles.row}>
              {(
                [
                  ["all", "Все"],
                  ["models", "С моделью"],
                  ["drafts", "Черновики"],
                ] as const
              ).map(([id, label]) => (
                <Pressable
                  key={id}
                  style={[
                    styles.chip,
                    filter === id && { borderColor: colors.text, backgroundColor: colors.panel2 },
                  ]}
                  onPress={() => setFilter(id)}
                >
                  <Text style={styles.chipText}>{label}</Text>
                </Pressable>
              ))}
            </View>
          </View>
          {visible.map((project) => (
            <Link key={project.id} href={`/project/${project.id}`} asChild>
              <Pressable style={[styles.projectCard, { flexDirection: "row", padding: 9, alignItems: "center" }]}>
                {thumbnailUrls[project.id] ? (
                  <Image
                    source={{ uri: thumbnailUrls[project.id] }}
                    accessibilityLabel={`Превью проекта ${project.name}`}
                    style={{ width: 112, height: 86, borderRadius: 7, backgroundColor: colors.viewport }}
                  />
                ) : (
                  <View style={{ width: 112, height: 86, borderRadius: 7, backgroundColor: colors.viewport, alignItems: "center", justifyContent: "center" }}>
                    <CubeIcon color={colors.muted} size={30} strokeWidth={1.3} />
                  </View>
                )}
                <View style={{ flex: 1, minWidth: 0, gap: 8, paddingHorizontal: 4 }}>
                  <Text style={[styles.heading, { fontSize: 16 }]} numberOfLines={2}>{project.name}</Text>
                  <View style={styles.row}>
                    <ProjectStatus draft={isDraft(project)} />
                    <Text style={styles.sectionSubtitle}>{relativeTime(project.updated_at ?? project.created_at, Date.now(), "ru")}</Text>
                  </View>
                </View>
                <ArrowRightIcon color={colors.muted} size={19} />
              </Pressable>
            </Link>
          ))}
          {visible.length === 0 && (
            <Text style={styles.muted}>Ничего не найдено. Измените поиск или фильтр.</Text>
          )}
        </>
      ))}
      {projects && projects.length === 0 && (
        <Text style={styles.muted}>Проектов пока нет — нажмите «+», чтобы начать.</Text>
      )}

    </ScrollView>
    </SafeAreaView>
  );
}
