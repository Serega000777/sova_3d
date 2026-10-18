import type { Listing } from "@physical-ai/contracts";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, TextInput, useWindowDimensions, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { CubeIcon, SearchIcon } from "@/src/AppIcons";
import { listingPrice } from "@/src/projects-screen";
import { useSession } from "@/src/session";
import { colors, elevationLow, radii, styles } from "@/src/theme";

export default function MarketScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const { session, client } = useSession();
  const [listings, setListings] = useState<Listing[]>([]);
  const [query, setQuery] = useState("");
  const [taking, setTaking] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client) return;
    setRefreshing(true);
    try {
      setListings(await client.searchListings({ sort: "popular", limit: 48 }));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }, [client]);

  useFocusEffect(useCallback(() => { void refresh(); }, [refresh]));

  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("ru");
    if (!needle) return listings;
    return listings.filter((listing) =>
      [listing.title, listing.creator_handle, listing.license_name]
        .some((value) => value.toLocaleLowerCase("ru").includes(needle)),
    );
  }, [listings, query]);

  async function take(listing: Listing) {
    if (!client || !session || taking) return;
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

  const contentWidth = Math.min(width - 32, 960);
  const columns = contentWidth >= 760 ? 3 : contentWidth >= 520 ? 2 : 1;
  const cardWidth = (contentWidth - (columns - 1) * 12) / columns;

  return (
    <SafeAreaView style={styles.screen} edges={["top"]}>
      <ScrollView
        style={styles.screen}
        contentContainerStyle={{ width: "100%", maxWidth: 992, alignSelf: "center", padding: 16, paddingBottom: 28, gap: 18 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />}
      >
        <View style={{ gap: 5 }}>
          <Text style={[styles.title, { fontSize: 29 }]}>Маркет</Text>
          <Text style={styles.muted}>Модели авторов с указанными ценой и лицензией.</Text>
        </View>

        <View style={{ height: 46, borderRadius: radii.control, backgroundColor: colors.panel, borderWidth: 1, borderColor: query ? colors.accent : colors.border, flexDirection: "row", alignItems: "center", paddingHorizontal: 13, gap: 10 }}>
          <SearchIcon color={colors.muted} size={20} />
          <TextInput value={query} onChangeText={setQuery} placeholder="Поиск в маркете" placeholderTextColor={colors.muted} clearButtonMode="while-editing" autoCorrect={false} style={{ flex: 1, color: colors.text, fontSize: 14 }} />
        </View>

        {error && <Text style={styles.error}>{error}</Text>}

        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 12 }}>
          {visible.map((listing) => (
            <View key={listing.id} style={{ width: cardWidth, borderRadius: radii.feature, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.panel, overflow: "hidden", ...elevationLow }}>
              <View accessibilityLabel="Изображение товара не передано маркетплейсом" style={{ height: 150, backgroundColor: colors.viewport, alignItems: "center", justifyContent: "center", gap: 8 }}>
                <CubeIcon color={colors.muted} size={42} strokeWidth={1.2} />
                <Text style={styles.sectionSubtitle}>ПРЕВЬЮ НЕДОСТУПНО</Text>
              </View>
              <View style={{ padding: 14, gap: 9 }}>
                <View style={{ minHeight: 48, gap: 4 }}>
                  <Text style={[styles.heading, { fontSize: 16 }]} numberOfLines={2}>{listing.title}</Text>
                  <Text style={styles.muted}>@{listing.creator_handle}</Text>
                </View>
                <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                  <View style={[styles.statusBadge, { backgroundColor: colors.accentWashStrong }]}>
                    <Text style={[styles.statusText, { color: colors.accent }]}>{listingPrice(listing.price_cents, listing.currency)}</Text>
                  </View>
                  <Text style={[styles.sectionSubtitle, { flex: 1, textAlign: "right" }]} numberOfLines={1}>{listing.license_name}</Text>
                </View>
                <Pressable
                  accessibilityRole="button"
                  disabled={taking !== null}
                  onPress={() => void take(listing)}
                  style={({ pressed }) => [styles.button, styles.buttonPrimary, { opacity: taking && taking !== listing.id ? 0.45 : pressed ? 0.78 : 1 }]}
                >
                  <Text style={styles.buttonText}>{taking === listing.id ? "Получаем…" : listing.price_cents === 0 ? "Получить" : "Купить"}</Text>
                </Pressable>
              </View>
            </View>
          ))}
        </View>

        {!refreshing && visible.length === 0 && (
          <View style={{ minHeight: 150, alignItems: "center", justifyContent: "center", gap: 6 }}>
            <Text style={styles.heading}>{query ? "Ничего не найдено" : "В маркете пока нет моделей"}</Text>
            <Text style={styles.sectionSubtitle}>{query ? "Попробуйте другой запрос" : "Потяните экран вниз, чтобы обновить"}</Text>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
