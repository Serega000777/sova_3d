import {
  getProjectGoal,
  PROJECT_GOALS,
  type Listing,
  type Project,
  type ProjectGoalId,
  type Template,
} from "@physical-ai/contracts";
import { Link, useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, TextInput, View } from "react-native";

import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

export default function Projects() {
  const router = useRouter();
  const { session, ready, client, signOut } = useSession();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  // F-004: the shelf — free listings you can take into your workspace right here
  const [market, setMarket] = useState<Listing[]>([]);
  const [taking, setTaking] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const [goalId, setGoalId] = useState<ProjectGoalId | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const goal = getProjectGoal(goalId);

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
          <Text style={styles.heading}>Physical AI 3D</Text>
          <Text style={styles.muted}>
            Describe an object, get a model you can edit and print. Sign in to start.
          </Text>
          <Pressable
            style={[styles.button, styles.buttonPrimary]}
            onPress={() => router.push("/sign-in")}
          >
            <Text style={styles.buttonText}>Sign in</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.muted} />
      }
    >
      {!goal ? (
        <View style={styles.card}>
          <Text style={styles.title}>Что будем создавать?</Text>
          <Text style={styles.muted}>Выбор задаёт первые инструменты и формат, но не ограничивает проект.</Text>
          {PROJECT_GOALS.map((item) => (
            <Pressable
              key={item.id}
              style={[styles.card, { backgroundColor: colors.panel2 }]}
              onPress={() => chooseGoal(item.id)}
            >
              <Text style={styles.heading}>{item.icon}  {item.title.ru} →</Text>
              <Text style={styles.muted}>{item.note.ru}</Text>
            </Pressable>
          ))}
        </View>
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
          <Text style={styles.heading}>Marketplace</Text>
          <Text style={styles.muted}>Models other makers put on the shelf.</Text>
          {market.map((listing) => (
            <View key={listing.id} style={[styles.row, { justifyContent: "space-between" }]}>
              <View style={{ flex: 1 }}>
                <Text style={styles.text}>{listing.title}</Text>
                <Text style={styles.muted}>
                  @{listing.creator_handle} ·{" "}
                  {listing.price_cents === 0
                    ? "free"
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
                  {taking === listing.id ? "…" : listing.price_cents === 0 ? "Get" : "Buy"}
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

      {projects?.map((project) => (
        <Link key={project.id} href={`/project/${project.id}`} asChild>
          <Pressable style={styles.card}>
            <Text style={styles.heading}>{project.name}</Text>
            <Text style={styles.muted}>
              {project.head_version_id ? "has model" : "empty"} ·{" "}
              {new Date(project.created_at).toLocaleDateString()}
            </Text>
          </Pressable>
        </Link>
      ))}
      {projects && projects.length === 0 && (
        <Text style={styles.muted}>No projects yet — create one above.</Text>
      )}

      <Pressable style={styles.button} onPress={signOut}>
        <Text style={styles.buttonText}>
          Sign out{session?.displayName || session?.address ? ` · ${session.displayName || session.address}` : ""}
        </Text>
      </Pressable>
    </ScrollView>
  );
}
