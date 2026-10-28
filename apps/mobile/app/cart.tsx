import type { Cart } from "@physical-ai/contracts";
import { Stack, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { listingPrice } from "@/src/projects-screen";
import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

export default function MarketplaceCart() {
  const router = useRouter();
  const { client, session } = useSession();
  const [cart, setCart] = useState<Cart | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client || !session) return;
    setError(null);
    try {
      setCart(await client.getCart(session.workspaceId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [client, session]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function remove(itemId: string) {
    if (!client || !session || busyId) return;
    setBusyId(itemId);
    setError(null);
    try {
      await client.removeFromCart(itemId, session.workspaceId);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <SafeAreaView style={styles.screen} edges={["bottom"]}>
      <Stack.Screen options={{ title: "Корзина" }} />
      <ScrollView
        style={styles.screen}
        contentContainerStyle={{ width: "100%", maxWidth: 900, alignSelf: "center", padding: 16, paddingBottom: 36, gap: 16 }}
      >
        <View style={{ gap: 5 }}>
          <Text style={styles.title}>Корзина</Text>
          <Text style={styles.muted}>Покупки будут добавлены в текущее рабочее пространство.</Text>
        </View>

        <Pressable accessibilityRole="button" onPress={() => router.push("/(tabs)/market")} style={styles.button}>
          <Text style={styles.buttonText}>Продолжить покупки</Text>
        </Pressable>

        {!cart && !error ? <Text style={styles.muted}>Загружаем корзину…</Text> : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
        {cart?.items.map((listing) => (
          <View key={listing.id} style={[styles.card, { gap: 10 }]}>
            <View style={{ gap: 3 }}>
              <Text style={styles.sectionTitle}>{listing.title}</Text>
              <Text style={styles.muted}>@{listing.creator_handle} · {listing.license_name}</Text>
              <Text style={[styles.statusText, { color: colors.accent }]}>{listingPrice(listing.price_cents, listing.currency)}</Text>
            </View>
            <Pressable
              accessibilityRole="button"
              disabled={busyId !== null}
              onPress={() => void remove(listing.id)}
              style={({ pressed }) => [styles.button, { opacity: busyId || pressed ? 0.65 : 1 }]}
            >
              <Text style={styles.buttonText}>{busyId === listing.id ? "Удаляем…" : "Удалить"}</Text>
            </Pressable>
          </View>
        ))}
        {cart && cart.items.length === 0 ? <View style={styles.card}><Text style={styles.muted}>Корзина пуста.</Text></View> : null}

        <View style={[styles.card, { gap: 12 }]}>
          <Text style={styles.sectionTitle}>Итого</Text>
          {cart && cart.totals.length > 0
            ? cart.totals.map((total) => (
              <Text key={total.currency} style={styles.statusText}>
                {listingPrice(total.amount_cents, total.currency)}
              </Text>
            ))
            : <Text style={styles.muted}>—</Text>}
          <Pressable accessibilityRole="button" accessibilityState={{ disabled: true }} disabled style={[styles.button, styles.buttonPrimary, { opacity: 0.55 }]}>
            <Text style={styles.buttonText}>Оплата — скоро</Text>
          </Pressable>
          <Text style={styles.muted}>Платёжный провайдер ещё не выбран.</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
