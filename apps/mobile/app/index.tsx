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
import { Link, Redirect, useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { Image, Pressable, RefreshControl, ScrollView, Text, TextInput, View } from "react-native";

import { CreateSheet } from "@/src/CreateSheet";
import { useIsTablet } from "@/src/layout";
import { listingPrice, templateVisual } from "@/src/projects-screen";
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
  const isTablet = useIsTablet();
  const { session, ready, client, signOut } = useSession();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [thumbnailUrls, setThumbnailUrls] = useState<Record<string, string>>({});
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
      const listings = await client.searchListings({ limit: 12 }).catch(() => []);
      setMarket(listings);
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
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Создать проект"
          style={({ pressed }) => [styles.createHero, pressed && { opacity: 0.88 }]}
          onPress={() => setSheetOpen(true)}
        >
          <View style={styles.createHeroIcon}>
            <Text style={{ color: colors.text, fontSize: 34, lineHeight: 36 }}>+</Text>
          </View>
          <View style={{ flex: 1, gap: 5 }}>
            <Text style={[styles.title, { fontSize: 25 }]}>Создать проект</Text>
            <Text style={[styles.text, { opacity: 0.9, lineHeight: 19 }]}>
              Скан, AI-модель или точная деталь — выберите готовый сценарий.
            </Text>
          </View>
          <Text style={{ color: colors.text, fontSize: 22 }}>→</Text>
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
                    <Text style={styles.templateGlyph}>{visual.glyph}</Text>
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

      {market.length > 0 && (
        <View style={styles.featureSection}>
          <SectionHeader
            title="Маркетплейс"
            subtitle="Модели авторов — цена, лицензия и данные публикации."
          />
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ gap: 10, paddingHorizontal: 1, paddingBottom: 8 }}
          >
            {market.map((listing) => (
              <View key={listing.id} style={styles.marketplaceCard}>
                {/* ListingOut has no public image URL. A foreign version thumbnail endpoint is
                    workspace-protected, so never substitute a made-up product image here. */}
                <View
                  accessibilityLabel="Изображение товара не передано маркетплейсом"
                  style={styles.marketplacePreview}
                >
                  <Text style={[styles.templateGlyph, { color: colors.muted }]}>◇</Text>
                  <Text style={styles.sectionSubtitle}>ПРЕВЬЮ НЕДОСТУПНО</Text>
                </View>
                <View style={styles.marketplaceBody}>
                  <Text style={styles.heading} numberOfLines={2}>{listing.title}</Text>
                  <Text style={styles.muted}>
                    @{listing.creator_handle}
                  </Text>
                  <View style={styles.row}>
                    <View style={[styles.statusBadge, { backgroundColor: colors.panel2 }]}>
                      <Text style={[styles.statusText, { color: colors.text }]}>
                        {listingPrice(listing.price_cents, listing.currency)}
                      </Text>
                    </View>
                    <Text style={styles.sectionSubtitle} numberOfLines={1}>
                      {listing.license_name}
                    </Text>
                  </View>
                  <Pressable
                    accessibilityRole="button"
                    style={({ pressed }) => [
                      styles.button,
                      { alignSelf: "stretch" },
                      pressed && { opacity: 0.8 },
                    ]}
                    disabled={taking !== null}
                    onPress={() => void take(listing)}
                  >
                    <Text style={styles.buttonText}>
                      {taking === listing.id ? "…" : listing.price_cents === 0 ? "Получить" : "Купить"}
                    </Text>
                  </Pressable>
                </View>
              </View>
            ))}
          </ScrollView>
        </View>
      )}

      <Pressable
        accessibilityRole="button"
        style={({ pressed }) => [styles.scannerRow, pressed && { opacity: 0.8 }]}
        onPress={() => router.push("/scan")}
      >
        <View style={styles.scannerIcon}>
          <Text style={{ color: colors.text, fontSize: 20 }}>◎</Text>
        </View>
        <View style={{ flex: 1, gap: 3 }}>
          <Text style={styles.heading}>3D-сканер</Text>
          <Text style={styles.sectionSubtitle}>
            Предмет, интерьер или дом — выберите сценарий съёмки.
          </Text>
        </View>
        <Text style={[styles.heading, { color: colors.muted }]}>→</Text>
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
          <View style={{ flex: 1, padding: 18 }}>
            {visible.map((project, index) => (
              <Link key={project.id} href={`/project/${project.id}`} asChild>
                <Pressable
                  style={index === 0 ? {
                    padding: 18,
                    marginBottom: 6,
                    borderRadius: 14,
                    borderLeftWidth: 3,
                    borderLeftColor: colors.muted,
                    backgroundColor: colors.panel2,
                    gap: 6,
                  } : {
                    paddingHorizontal: 16,
                    paddingVertical: 15,
                    borderTopWidth: 1,
                    borderTopColor: colors.border,
                    gap: 5,
                  }}
                >
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
                    {thumbnailUrls[project.id] ? (
                      <Image
                        source={{ uri: thumbnailUrls[project.id] }}
                        accessibilityLabel={`Превью проекта ${project.name}`}
                        style={{ width: 88, height: 64, borderRadius: 6, backgroundColor: colors.viewport }}
                      />
                    ) : (
                      <View style={{ width: 88, height: 64, borderRadius: 6, backgroundColor: colors.viewport, alignItems: "center", justifyContent: "center" }}>
                        <Text style={[styles.title, { color: colors.muted }]}>{isDraft(project) ? "◌" : "◈"}</Text>
                      </View>
                    )}
                    <View style={{ flex: 1, gap: 5 }}>
                      <Text style={index === 0 ? [styles.title, { fontSize: 18 }] : styles.heading}>
                        {project.name}
                      </Text>
                      <View style={styles.row}>
                        <ProjectStatus draft={isDraft(project)} />
                        <Text style={styles.sectionSubtitle}>
                          {relativeTime(project.updated_at ?? project.created_at, Date.now(), "ru")}
                        </Text>
                      </View>
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
              <Pressable style={styles.projectCard}>
                {thumbnailUrls[project.id] ? (
                  <Image
                    source={{ uri: thumbnailUrls[project.id] }}
                    accessibilityLabel={`Превью проекта ${project.name}`}
                    style={styles.projectPreview}
                  />
                ) : (
                  <View style={[styles.projectPreview, { height: 112, alignItems: "center", justifyContent: "center" }]}>
                    <Text style={[styles.title, { color: colors.muted }]}>{isDraft(project) ? "◌" : "◈"}</Text>
                  </View>
                )}
                <Text style={styles.heading}>{project.name}</Text>
                <View style={styles.row}>
                  <ProjectStatus draft={isDraft(project)} />
                  <Text style={styles.sectionSubtitle}>
                    {relativeTime(project.updated_at ?? project.created_at, Date.now(), "ru")}
                  </Text>
                </View>
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
        style={styles.floatingAction}
      >
        <Text style={{ color: "#fff", fontSize: 32, lineHeight: 34 }}>+</Text>
      </Pressable>
    )}
    <CreateSheet visible={sheetOpen} onClose={() => setSheetOpen(false)} onChoose={chooseScenario} />
    </View>
  );
}
