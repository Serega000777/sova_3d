import type { CreatorPage } from "@physical-ai/contracts";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { listingPrice } from "@/src/projects-screen";
import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

export default function MarketplaceCreator() {
  const router = useRouter();
  const { handle } = useLocalSearchParams<{ handle: string }>();
  const { client } = useSession();
  const [page, setPage] = useState<CreatorPage | null>(null);
  const [myHandle, setMyHandle] = useState<string | null>(null);
  const [following, setFollowing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client || !handle) return;
    setError(null);
    try {
      const [nextPage, ownProfile] = await Promise.all([
        client.creatorPage(handle),
        client.myCreatorProfile().catch(() => null),
      ]);
      setPage(nextPage);
      setFollowing(nextPage.profile.following);
      setMyHandle(ownProfile?.handle ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [client, handle]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function toggleFollow() {
    if (!client || !page || busy || page.profile.handle === myHandle) return;
    setBusy(true);
    setError(null);
    try {
      const profile = following
        ? await client.unfollowCreator(page.profile.handle)
        : await client.followCreator(page.profile.handle);
      setFollowing(profile.following);
      setPage((current) => current ? { ...current, profile } : current);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={styles.screen} edges={["bottom"]}>
      <Stack.Screen options={{ title: page?.profile.display_name ?? `@${handle}` }} />
      <ScrollView
        style={styles.screen}
        contentContainerStyle={{ width: "100%", maxWidth: 900, alignSelf: "center", padding: 16, paddingBottom: 36, gap: 16 }}
      >
        {!page && !error ? <Text style={styles.muted}>Загружаем страницу автора…</Text> : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
        {page ? (
          <>
            <View style={[styles.card, { gap: 12 }]}>
              <View style={{ gap: 4 }}>
                <Text style={styles.title}>{page.profile.display_name}</Text>
                <Text style={styles.muted}>@{page.profile.handle}</Text>
                <Text style={styles.sectionSubtitle}>{page.profile.followers} подписчиков · {page.profile.listings} публикаций</Text>
              </View>
              {page.profile.bio ? <Text style={{ color: colors.text, lineHeight: 22 }}>{page.profile.bio}</Text> : null}
              {page.profile.handle !== myHandle ? (
                <Pressable
                  accessibilityRole="button"
                  disabled={busy}
                  onPress={() => void toggleFollow()}
                  style={({ pressed }) => [styles.button, following ? null : styles.buttonPrimary, { opacity: busy || pressed ? 0.7 : 1 }]}
                >
                  <Text style={styles.buttonText}>{busy ? "Сохраняем…" : following ? "Вы подписаны ✓" : "Подписаться"}</Text>
                </Pressable>
              ) : null}
            </View>

            {(page.collections ?? []).map((collection) => (
              <View key={collection.id} style={[styles.card, { gap: 8 }]}>
                <Text style={styles.sectionTitle}>{collection.title}</Text>
                {collection.description ? <Text style={styles.muted}>{collection.description}</Text> : null}
                <Text style={styles.sectionSubtitle}>{collection.listings.length} моделей</Text>
              </View>
            ))}

            <View style={{ gap: 10 }}>
              <Text style={styles.sectionTitle}>Публикации</Text>
              {page.listings.map((listing) => (
                <Pressable
                  key={listing.id}
                  accessibilityRole="link"
                  onPress={() => router.push(`/market/${listing.id}`)}
                  style={({ pressed }) => [styles.card, { gap: 7, opacity: pressed ? 0.72 : 1 }]}
                >
                  <Text style={styles.sectionTitle}>{listing.title}</Text>
                  <Text style={styles.muted}>{listing.category} · {listing.license_name}</Text>
                  <Text style={[styles.statusText, { color: colors.accent }]}>{listingPrice(listing.price_cents, listing.currency)}</Text>
                </Pressable>
              ))}
              {page.listings.length === 0 ? <View style={styles.card}><Text style={styles.muted}>Публикаций пока нет.</Text></View> : null}
            </View>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
