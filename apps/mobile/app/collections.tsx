import type { Listing, MarketplaceFile, Order } from "@physical-ai/contracts";
import { Redirect, useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Linking, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/src/session";
import { verifiedMarketplaceDownloadUrl } from "@/src/marketplace-download";
import { colors, styles } from "@/src/theme";

function fileLabel(file: MarketplaceFile): string {
  const labels = file.labels.length > 0 ? file.labels.join(" · ") : file.role;
  return `${labels} · ${file.format.toUpperCase()} · ${(file.byte_size / 1_048_576).toFixed(2)} МБ`;
}

export default function CollectionsScreen() {
  const router = useRouter();
  const { session, ready, client } = useSession();
  const [favorites, setFavorites] = useState<Listing[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [filesByOrder, setFilesByOrder] = useState<Record<string, MarketplaceFile[]>>({});
  const [refreshing, setRefreshing] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client) return;
    setRefreshing(true);
    try {
      const [nextFavorites, nextOrders] = await Promise.all([
        client.favoriteListings(),
        client.myOrders(),
      ]);
      const completed = nextOrders.filter((order) => order.status === "completed");
      const files = await Promise.all(completed.map(async (order) => (
        [order.id, await client.orderFiles(order.id)] as const
      )));
      setFavorites(nextFavorites);
      setOrders(completed);
      setFilesByOrder(Object.fromEntries(files));
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setRefreshing(false);
    }
  }, [client]);

  useFocusEffect(useCallback(() => { void refresh(); }, [refresh]));

  async function download(file: MarketplaceFile) {
    if (!client || downloading) return;
    setDownloading(file.asset_id);
    setError(null);
    try {
      const target = await client.download(file.asset_id);
      const url = verifiedMarketplaceDownloadUrl(file, target);
      if (!url) throw new Error("Сервер вернул ссылку не на выбранный доставленный файл.");
      await Linking.openURL(url);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setDownloading(null);
    }
  }

  if (!ready) return <View style={styles.screen} />;
  if (!session) return <Redirect href="/sign-in" />;

  return (
    <SafeAreaView style={styles.screen} edges={["bottom"]}>
      <ScrollView
        style={styles.screen}
        contentContainerStyle={[styles.content, { paddingBottom: 40, gap: 18 }]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />}
      >
        <View style={{ gap: 4 }}>
          <Text style={[styles.title, { fontSize: 30 }]}>Избранное и загрузки</Text>
          <Text style={styles.muted}>Только сохранённые сервером товары и файлы завершённых покупок.</Text>
        </View>
        {error ? <Text style={styles.error}>{error}</Text> : null}

        <View style={{ gap: 10 }}>
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <Text style={styles.sectionTitle}>Избранное · {favorites.length}</Text>
            <Pressable onPress={() => router.push("/market")}><Text style={{ color: colors.accent }}>Открыть маркет →</Text></Pressable>
          </View>
          {favorites.length > 0 ? favorites.map((listing) => (
            <View key={listing.id} style={[styles.card, { gap: 4 }]}>
              <Text style={styles.heading}>{listing.title}</Text>
              <Text style={styles.muted}>@{listing.creator_handle} · {listing.license_name}</Text>
            </View>
          )) : <Text style={styles.muted}>Сохранённых товаров пока нет.</Text>}
        </View>

        <View style={{ gap: 10 }}>
          <Text style={styles.sectionTitle}>Покупки и файлы · {orders.length}</Text>
          {orders.length > 0 ? orders.map((order) => {
            const files = filesByOrder[order.id] ?? [];
            return (
              <View key={order.id} style={[styles.card, { gap: 9 }]}>
                <Text style={styles.heading}>Заказ {order.id.slice(0, 8)} · {order.status}</Text>
                <Text style={styles.muted}>{new Date(order.created_at).toLocaleString("ru-RU")} · {order.currency} {(order.price_cents / 100).toFixed(2)}</Text>
                {order.project_id ? (
                  <Pressable style={styles.button} onPress={() => router.push(`/project/${order.project_id}`)}>
                    <Text style={styles.buttonText}>Открыть полученный проект</Text>
                  </Pressable>
                ) : null}
                {order.status === "completed" && files.length === 0 ? (
                  <Text style={styles.muted}>В заказе нет отдельных доставленных файлов.</Text>
                ) : files.map((file) => (
                  <Pressable
                    key={file.asset_id}
                    accessibilityRole="button"
                    disabled={downloading !== null}
                    style={[styles.button, downloading === file.asset_id && { opacity: 0.5 }]}
                    onPress={() => void download(file)}
                  >
                    <Text style={styles.buttonText}>{downloading === file.asset_id ? "Открываем…" : fileLabel(file)}</Text>
                  </Pressable>
                ))}
              </View>
            );
          }) : <Text style={styles.muted}>Завершённых покупок пока нет.</Text>}
        </View>

        <View style={[styles.card, { borderColor: colors.yellow, gap: 4 }]}>
          <Text style={styles.heading}>Граница</Text>
          <Text style={styles.muted}>Это библиотека цифровых покупок. Она не является очередью физического производства или историей локальных файлов устройства.</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
