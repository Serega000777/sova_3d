import type { Listing } from "@physical-ai/contracts";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { listingPrice } from "@/src/projects-screen";
import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

export default function MarketplaceFollowingFeed() {
  const router = useRouter();
  const { client } = useSession();
  const [listings, setListings] = useState<Listing[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client) return;
    setRefreshing(true);
    setError(null);
    try {
      setListings(await client.marketplaceFeed());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoaded(true);
      setRefreshing(false);
    }
  }, [client]);

  useFocusEffect(useCallback(() => { void refresh(); }, [refresh]));

  return (
    <SafeAreaView style={styles.screen} edges={["bottom"]}>
      <Stack.Screen options={{ title: "Лента подписок" }} />
      <ScrollView
        style={styles.screen}
        contentContainerStyle={{ width: "100%", maxWidth: 900, alignSelf: "center", padding: 16, paddingBottom: 36, gap: 14 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />}
      >
        <View style={{ gap: 5 }}>
          <Text style={styles.title}>Лента подписок</Text>
          <Text style={styles.muted}>Новые публикации только тех авторов, на которых вы подписаны.</Text>
        </View>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        {!loaded ? <Text style={styles.muted}>Загружаем публикации…</Text> : null}
        {listings.map((listing) => (
          <Pressable
            key={listing.id}
            accessibilityRole="link"
            onPress={() => router.push(`/market/${listing.id}`)}
            style={({ pressed }) => [styles.card, { gap: 7, opacity: pressed ? 0.72 : 1 }]}
          >
            <Text style={styles.sectionTitle}>{listing.title}</Text>
            <Text style={styles.muted}>@{listing.creator_handle} · {listing.category}</Text>
            <Text style={[styles.statusText, { color: colors.accent }]}>{listingPrice(listing.price_cents, listing.currency)}</Text>
          </Pressable>
        ))}
        {loaded && listings.length === 0 && !error ? (
          <View style={[styles.card, { gap: 8 }]}>
            <Text style={styles.sectionTitle}>Публикаций пока нет</Text>
            <Text style={styles.muted}>Подпишитесь на автора в карточке модели — его новые работы появятся здесь.</Text>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
