import type {
  ProjectSummary,
  ThumbnailAngle,
  ThumbnailUrlSet,
  VersionHistoryItem,
} from "@physical-ai/contracts";
import { Redirect, Stack, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Image,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useIsTablet } from "@/src/layout";
import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";
import { VersionImageComparison } from "@/src/VersionImageComparison";

function formatAssetBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

function versionAuthor(version: VersionHistoryItem): string {
  return version.creator_name ?? (version.created_by ? version.created_by.slice(0, 8) : "Система");
}

export default function ProjectHistoryScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const isTablet = useIsTablet();
  const { client, ready, session } = useSession();
  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [history, setHistory] = useState<VersionHistoryItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [thumbnailAngle, setThumbnailAngle] = useState<ThumbnailAngle>("iso");
  const [thumbnailUrls, setThumbnailUrls] = useState<Record<string, ThumbnailUrlSet>>({});
  const [comment, setComment] = useState("");
  const [commentDirty, setCommentDirty] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client || !id) return;
    setRefreshing(true);
    try {
      const [summary, versions] = await Promise.all([
        client.getProject(id),
        client.listVersionHistory(id),
      ]);
      setProject(summary);
      setHistory(versions);
      setSelectedId((current) =>
        versions.some((version) => version.id === current)
          ? current
          : summary.head_version?.id ?? versions[0]?.id ?? null,
      );
      setError(null);

      const entries = await Promise.all(
        versions.map(async (version, index) => {
          const hasThumbnail = version.assets.some((asset) => asset.role === "thumbnail");
          if (!hasThumbnail && index >= 24) return null;
          const urls = await client
            .versionThumbnailUrls(version.id, version.assets)
            .catch(() => ({} as ThumbnailUrlSet));
          return Object.keys(urls).length ? ([version.id, urls] as const) : null;
        }),
      );
      setThumbnailUrls(
        Object.fromEntries(
          entries.filter((entry): entry is readonly [string, ThumbnailUrlSet] => entry !== null),
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }, [client, id]);

  useFocusEffect(
    useCallback(() => {
      void refresh();
    }, [refresh]),
  );

  const selectedIndex = history.findIndex((version) => version.id === selectedId);
  const selected = selectedIndex >= 0 ? history[selectedIndex] : null;
  const comparison = selected
    ? history[selectedIndex + 1] ?? history[selectedIndex - 1] ?? null
    : null;

  useEffect(() => {
    setComment(selected?.comment ?? "");
    setCommentDirty(false);
  }, [selected?.id, selected?.comment]);

  const saveComment = useCallback(async () => {
    if (!client || !selected || !commentDirty || busy) return;
    setBusy("Сохраняем комментарий");
    setError(null);
    try {
      await client.putVersionComment(selected.id, comment, selected.comment_revision);
      await refresh();
      setNotice("Комментарий версии сохранён.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }, [busy, client, comment, commentDirty, refresh, selected]);

  const restoreSelected = useCallback(async () => {
    if (!client || !id || !selected || busy) return;
    setBusy(`Восстанавливаем v${selected.sequence_no}`);
    setError(null);
    try {
      const restored = await client.rollback(
        id,
        `v${selected.sequence_no}`,
        project?.head_version?.id ?? null,
      );
      await refresh();
      setSelectedId(restored.id);
      setNotice(`v${selected.sequence_no} восстановлена как новая неизменяемая версия.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }, [busy, client, id, project?.head_version?.id, refresh, selected]);

  const confirmRestore = useCallback(() => {
    if (!selected) return;
    Alert.alert(
      `Восстановить v${selected.sequence_no}?`,
      "Текущая история не изменится: сервер создаст новую версию поверх текущей.",
      [
        { text: "Отмена", style: "cancel" },
        { text: "Восстановить", onPress: () => void restoreSelected() },
      ],
    );
  }, [restoreSelected, selected]);

  const angleControls = (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
      {(["front", "iso", "top"] as const).map((angle) => (
        <Pressable
          key={angle}
          onPress={() => setThumbnailAngle(angle)}
          style={[styles.chip, thumbnailAngle === angle && { borderColor: colors.selection }]}
        >
          <Text style={[styles.chipText, thumbnailAngle === angle && { color: colors.selection }]}>
            {angle === "front" ? "Спереди" : angle === "iso" ? "Изометрия" : "Сверху"}
          </Text>
        </Pressable>
      ))}
    </ScrollView>
  );

  const timeline = (
    <View
      style={[styles.card, { flex: isTablet ? 0.72 : undefined, width: isTablet ? undefined : "100%", gap: 0 }]}
      accessibilityLabel="История изменений проекта"
    >
      <Text style={[styles.heading, { marginBottom: 14 }]}>История изменений</Text>
      {history.map((version, index) => {
        const isSelected = version.id === selected?.id;
        const isHead = version.id === project?.head_version?.id;
        return (
          <Pressable
            key={version.id}
            accessibilityRole="button"
            accessibilityState={{ selected: isSelected }}
            onPress={() => {
              setSelectedId(version.id);
              setNotice(null);
            }}
            style={{ flexDirection: "row", gap: 12, minHeight: 82 }}
          >
            <View style={{ width: 18, alignItems: "center" }}>
              <View
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: 7,
                  borderWidth: 3,
                  borderColor: isSelected ? colors.accent : colors.muted,
                  backgroundColor: colors.panel,
                }}
              />
              {index < history.length - 1 ? (
                <View style={{ flex: 1, width: 2, backgroundColor: colors.border }} />
              ) : null}
            </View>
            <View style={{ flex: 1, paddingBottom: 15, gap: 3 }}>
              <View style={[styles.row, { justifyContent: "space-between" }]}>
                <Text style={[styles.heading, isSelected && { color: colors.accent }]}>
                  v{version.sequence_no} · {version.label ?? "Без названия"}
                </Text>
                <View style={[styles.chip, isHead && { borderColor: colors.green }]}>
                  <Text style={styles.chipText}>{isHead ? "Текущая" : `Версия ${version.sequence_no}`}</Text>
                </View>
              </View>
              <Text style={styles.sectionSubtitle}>
                {new Date(version.created_at).toLocaleString("ru-RU")} · {versionAuthor(version)}
              </Text>
              <Text style={styles.sectionSubtitle}>{formatAssetBytes(version.total_asset_bytes)}</Text>
              {version.comment ? <Text style={styles.muted}>{version.comment}</Text> : null}
            </View>
          </Pressable>
        );
      })}
      {!refreshing && history.length === 0 ? <Text style={styles.muted}>В проекте ещё нет версий.</Text> : null}
    </View>
  );

  const detail = selected ? (
    <View style={{ flex: isTablet ? 1.28 : undefined, width: isTablet ? undefined : "100%", gap: 12 }}>
      <View style={[styles.card, { gap: 12 }]} accessibilityLabel={`Выбранная версия ${selected.sequence_no}`}>
        <View style={[styles.row, { justifyContent: "space-between" }]}>
          <View style={{ flex: 1, gap: 3 }}>
            <Text style={styles.title}>v{selected.sequence_no} · {selected.label ?? "Без названия"}</Text>
            <Text style={styles.sectionSubtitle}>
              {versionAuthor(selected)} · {new Date(selected.created_at).toLocaleString("ru-RU")}
            </Text>
          </View>
          <Pressable style={styles.button} onPress={() => router.push(`/project/${id}`)}>
            <Text style={styles.buttonText}>Открыть в редакторе</Text>
          </Pressable>
        </View>
        {angleControls}
        {thumbnailUrls[selected.id]?.[thumbnailAngle] ? (
          <Image
            source={{ uri: thumbnailUrls[selected.id]?.[thumbnailAngle] }}
            accessibilityLabel={`Превью версии ${selected.sequence_no}: ${thumbnailAngle}`}
            resizeMode="cover"
            style={{ width: "100%", height: isTablet ? 280 : 210, borderRadius: 12, backgroundColor: colors.viewport }}
          />
        ) : (
          <View style={{ height: isTablet ? 280 : 210, borderRadius: 12, backgroundColor: colors.viewport, alignItems: "center", justifyContent: "center" }}>
            <Text style={styles.muted}>Для этого ракурса нет канонического превью</Text>
          </View>
        )}
      </View>

      {comparison ? (
        <View style={[styles.card, { gap: 10 }]} accessibilityLabel="Сравнение версий">
          <Text style={styles.heading}>Сравнение версий</Text>
          <Text style={styles.muted}>Проведите по изображению: v{selected.sequence_no} ↔ v{comparison.sequence_no}</Text>
          <VersionImageComparison
            beforeUrl={thumbnailUrls[comparison.id]?.[thumbnailAngle] ?? null}
            currentUrl={thumbnailUrls[selected.id]?.[thumbnailAngle] ?? null}
            beforeLabel={`v${comparison.sequence_no}`}
            currentLabel={`v${selected.sequence_no}`}
            height={isTablet ? 250 : 190}
          />
        </View>
      ) : null}

      <View style={[styles.card, { gap: 10 }]}>
        <Text style={styles.heading}>Комментарий к v{selected.sequence_no}</Text>
        <TextInput
          accessibilityLabel={`Комментарий к версии ${selected.sequence_no}`}
          multiline
          maxLength={2000}
          placeholder="Что изменено и что проверить"
          placeholderTextColor={colors.muted}
          value={comment}
          onChangeText={(value) => {
            setComment(value);
            setCommentDirty(true);
          }}
          style={[styles.input, { minHeight: 82, textAlignVertical: "top" }]}
        />
        <View style={[styles.row, { justifyContent: "space-between" }]}>
          <Text style={styles.sectionSubtitle}>{comment.length}/2000</Text>
          <Pressable
            disabled={!commentDirty || Boolean(busy)}
            onPress={() => void saveComment()}
            style={[styles.button, (!commentDirty || Boolean(busy)) && { opacity: 0.45 }]}
          >
            <Text style={styles.buttonText}>Сохранить комментарий</Text>
          </Pressable>
        </View>
      </View>

      {selected.id !== project?.head_version?.id ? (
        <Pressable
          accessibilityRole="button"
          disabled={Boolean(busy)}
          onPress={confirmRestore}
          style={[styles.button, styles.buttonPrimary, { minHeight: 52, justifyContent: "center" }, busy && { opacity: 0.5 }]}
        >
          <Text style={styles.buttonText}>Восстановить v{selected.sequence_no} как новую версию</Text>
        </Pressable>
      ) : (
        <View style={[styles.card, { borderColor: colors.green }]}>
          <Text style={[styles.heading, { color: colors.green }]}>Это текущая версия проекта</Text>
          <Text style={styles.muted}>История неизменяема; восстановление старой версии добавит новую запись.</Text>
        </View>
      )}
    </View>
  ) : null;

  if (!ready) return <View style={styles.screen} />;
  if (!session) return <Redirect href="/sign-in" />;

  return (
    <SafeAreaView style={styles.screen} edges={["bottom"]}>
      <Stack.Screen options={{ title: project?.name ? `История · ${project.name}` : "История проекта" }} />
      <ScrollView
        style={styles.screen}
        contentContainerStyle={[
          styles.content,
          { paddingBottom: 40 },
          isTablet && { width: "100%", maxWidth: 1180, alignSelf: "center", paddingHorizontal: 28 },
        ]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.muted} />}
      >
        <View style={[styles.row, { justifyContent: "space-between" }]}>
          <View style={{ flex: 1, gap: 3 }}>
            <Text style={[styles.title, { fontSize: isTablet ? 30 : 26 }]}>История проекта</Text>
            <Text style={styles.muted}>
              {project?.name ?? "Проект"} · {history.length} {history.length === 1 ? "версия" : "версий"}
            </Text>
          </View>
          <Pressable style={styles.button} onPress={() => router.back()}>
            <Text style={styles.buttonText}>← Проект</Text>
          </Pressable>
        </View>

        {error ? <Text style={[styles.muted, { color: colors.red }]}>{error}</Text> : null}
        {busy ? <Text style={styles.muted}>{busy}…</Text> : null}
        {notice ? <Text style={[styles.muted, { color: colors.green }]}>{notice}</Text> : null}

        <View style={{ flexDirection: isTablet ? "row" : "column", alignItems: "flex-start", gap: 12 }}>
          {timeline}
          {detail}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
