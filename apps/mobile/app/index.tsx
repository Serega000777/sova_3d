import {
  getProjectGoal,
  isDraft,
  libraryView,
  relativeTime,
  type CreateScenario,
  type LibraryFilter,
  type Listing,
  type Project,
  type ProjectGoalId,
  type Template,
} from "@physical-ai/contracts";
import { Link, useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, TextInput, View } from "react-native";

import { CreateSheet } from "@/src/CreateSheet";
import { useIsTablet } from "@/src/layout";
import { Onboarding } from "@/src/Onboarding";
import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

export default function Projects() {
  return (
    <>
      <ProjectsHome />
      <Onboarding language="ru" />
    </>
  );
}

function ProjectsHome() {
  const router = useRouter();
  const isTablet = useIsTablet();
  const { session, ready, client, signOut } = useSession();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  // F-004: the shelf — free listings you can take into your workspace right here
  const [market, setMarket] = useState<Listing[]>([]);
  const [taking, setTaking] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const [goalId, setGoalId] = useState<ProjectGoalId | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<LibraryFilter>("all");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
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
    setError(null);
  }

  /** A Create-sheet scenario: scans enter capture, the rest start a project with smart defaults. */
  function chooseScenario(scenario: CreateScenario) {
    if (scenario.goal) chooseGoal(scenario.goal);
  }

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
      setProjects(await client.listProjects(session.workspaceId));
      setTemplates(await client.listTemplates());
      setMarket(await client.searchListings({ limit: 12 }).catch(() => []));
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
  /** F-004: a listing becomes a project of yours, credited to its creator. */
  async function take(listing: Listing) {
    if (!client || !session) return;
    setTaking(listing.id);
    setError(null);
    try {
      const acquired = await client.acquireListing(listing.id, session.workspaceId);
      router.push(`/project/${acquired.project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setTaking(null);
    }
  }

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
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
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
      {!goal ? (
        <Pressable style={[styles.card, { backgroundColor: colors.accent2, borderColor: colors.accent2 }]} onPress={() => setSheetOpen(true)}>
          <Text style={styles.title}>+  Создать</Text>
          <Text style={[styles.text, { opacity: 0.9 }]}>
            Скан комнаты, предмета или здания, AI-модель, деталь — готовые сценарии с подсказками.
          </Text>
        </Pressable>
      ) : (
        <View style={styles.card}>
          <Text style={styles.title}>{goal.icon}  {goal.title.ru}</Text>
          <Text style={styles.muted}>{goal.note.ru}</Text>
          <TextInput
            style={styles.input}
            value={name}
            onChangeText={setName}
            placeholder="Название проекта"
            placeholderTextColor={colors.muted}
          />
          <View style={styles.row}>
            <Pressable
              style={styles.button}
              disabled={creating}
              onPress={() => { setGoalId(null); setName(""); }}
            >
              <Text style={styles.buttonText}>← Назад</Text>
            </Pressable>
            <Pressable
              style={[styles.button, styles.buttonPrimary, (!name.trim() || creating) && { opacity: 0.5 }]}
              disabled={!name.trim() || creating}
              onPress={() => void createFromGoal()}
            >
              <Text style={styles.buttonText}>{creating ? "Создаём…" : "Открыть редактор →"}</Text>
            </Pressable>
          </View>
        </View>
      )}

      {templates.length > 0 && (
        <View style={styles.card}>
          <Text style={styles.heading}>Начните с шаблона</Text>
          <Text style={styles.muted}>Готовые детали, которые точно построятся.</Text>
          <View style={styles.row}>
            {templates.map((template) => (
              <Pressable
                key={template.id}
                style={[styles.chip, starting === template.id && { borderColor: colors.accent }]}
                disabled={starting !== null}
                onPress={() => void startTemplate(template)}
              >
                <Text style={styles.chipText}>
                  {starting === template.id ? "Строим…" : template.title_ru}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>
      )}

      {market.length > 0 && (
        <View style={styles.card}>
          <Text style={styles.heading}>Маркетплейс</Text>
          <Text style={styles.muted}>Модели, которыми поделились другие авторы.</Text>
          {market.map((listing) => (
            <View key={listing.id} style={[styles.row, { justifyContent: "space-between" }]}>
              <View style={{ flex: 1 }}>
                <Text style={styles.text}>{listing.title}</Text>
                <Text style={styles.muted}>
                  @{listing.creator_handle} ·{" "}
                  {listing.price_cents === 0
                    ? "бесплатно"
                    : `${(listing.price_cents / 100).toFixed(2)} ${listing.currency}`}{" "}
                  · {listing.license_name}
                </Text>
              </View>
              <Pressable
                style={styles.chip}
                disabled={taking !== null}
                onPress={() => void take(listing)}
              >
                <Text style={styles.chipText}>
                  {taking === listing.id ? "…" : listing.price_cents === 0 ? "Получить" : "Купить"}
                </Text>
              </Pressable>
            </View>
          ))}
        </View>
      )}

      <Pressable style={styles.card} onPress={() => router.push("/scan")}>
        <Text style={styles.heading}>3D-сканер</Text>
        <Text style={styles.muted}>
          Предмет, интерьер или дом — выберите сценарий съёмки.
        </Text>
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
                  style={[styles.chip, filter === id && { borderColor: colors.accent, backgroundColor: "rgba(91,156,255,0.16)" }]}
                  onPress={() => setFilter(id)}
                >
                  <Text style={styles.chipText}>{label}</Text>
                </Pressable>
              ))}
            </View>
          </View>
          <View style={{ flex: 1, padding: 18 }}>
            {visible.map((project, index) => (
              <Link key={project.id} href={`/project/${project.id}`} asChild>
                <Pressable
                  style={index === 0 ? {
                    padding: 18,
                    marginBottom: 6,
                    borderRadius: 14,
                    borderLeftWidth: 3,
                    borderLeftColor: colors.accent,
                    backgroundColor: "rgba(91,156,255,0.09)",
                    gap: 6,
                  } : {
                    paddingHorizontal: 16,
                    paddingVertical: 15,
                    borderTopWidth: 1,
                    borderTopColor: colors.border,
                    gap: 5,
                  }}
                >
                  <Text style={index === 0 ? [styles.title, { fontSize: 18 }] : styles.heading}>
                    {project.name}
                  </Text>
                  <Text style={styles.muted}>
                    {isDraft(project) ? "Черновик" : "Есть модель"} ·{" "}
                    {relativeTime(project.updated_at ?? project.created_at, Date.now(), "ru")}
                  </Text>
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
                  style={[styles.chip, filter === id && { borderColor: colors.accent, backgroundColor: "rgba(91,156,255,0.16)" }]}
                  onPress={() => setFilter(id)}
                >
                  <Text style={styles.chipText}>{label}</Text>
                </Pressable>
              ))}
            </View>
          </View>
          {visible.map((project) => (
            <Link key={project.id} href={`/project/${project.id}`} asChild>
              <Pressable style={styles.card}>
                <Text style={styles.heading}>{project.name}</Text>
                <Text style={styles.muted}>
                  {isDraft(project) ? "Черновик" : "Есть модель"} ·{" "}
                  {relativeTime(project.updated_at ?? project.created_at, Date.now(), "ru")}
                </Text>
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

      <Pressable style={styles.button} onPress={signOut}>
        <Text style={styles.buttonText}>
          Выйти{session?.displayName || session?.address ? ` · ${session.displayName || session.address}` : ""}
        </Text>
      </Pressable>
    </ScrollView>
    {!goal && (
      <Pressable
        accessibilityLabel="Создать"
        onPress={() => setSheetOpen(true)}
        style={{
          position: "absolute",
          right: 20,
          bottom: 24,
          width: 60,
          height: 60,
          borderRadius: 30,
          backgroundColor: colors.accent2,
          alignItems: "center",
          justifyContent: "center",
          elevation: 6,
          shadowColor: "#000",
          shadowOpacity: 0.4,
          shadowRadius: 8,
          shadowOffset: { width: 0, height: 4 },
        }}
      >
        <Text style={{ color: "#fff", fontSize: 32, lineHeight: 34 }}>+</Text>
      </Pressable>
    )}
    <CreateSheet visible={sheetOpen} onClose={() => setSheetOpen(false)} onChoose={chooseScenario} />
    </View>
  );
}
