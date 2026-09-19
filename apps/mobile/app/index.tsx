import type { Listing, Project, Template } from "@physical-ai/contracts";
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
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

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
      <View style={styles.card}>
        <Text style={styles.heading}>New project</Text>
        <TextInput
          style={styles.input}
          value={name}
          onChangeText={setName}
          placeholder="Project name"
          placeholderTextColor={colors.muted}
        />
        <Pressable
          style={[styles.button, styles.buttonPrimary, !name.trim() && { opacity: 0.5 }]}
          disabled={!name.trim()}
          onPress={async () => {
            if (!client || !session) return;
            await client.createProject({ workspace_id: session.workspaceId, name: name.trim() });
            setName("");
            await refresh();
          }}
        >
          <Text style={styles.buttonText}>Create</Text>
        </Pressable>
      </View>

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
        <Text style={styles.heading}>Scan an object</Text>
        <Text style={styles.muted}>
          Walk around it with the camera and get a model you can edit and print.
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
        <Text style={styles.buttonText}>Sign out</Text>
      </Pressable>
    </ScrollView>
  );
}
