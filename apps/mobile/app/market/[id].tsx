import type { Listing } from "@physical-ai/contracts";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { Image, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { CubeIcon } from "@/src/AppIcons";
import { listingPrice } from "@/src/projects-screen";
import { useSession } from "@/src/session";
import { colors, radii, styles } from "@/src/theme";

interface SavedThumbnail {
  angle: string;
  asset_id: string;
}

function listingThumbnails(listing: Listing): SavedThumbnail[] {
  const thumbnails = listing.thumbnails ?? [];
  if (thumbnails.length > 0) return thumbnails;
  return listing.thumbnail_asset_id
    ? [{ angle: "iso", asset_id: listing.thumbnail_asset_id }]
    : [];
}

export default function MarketplaceListing() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { client, session } = useSession();
  const [listing, setListing] = useState<Listing | null>(null);
  const [thumbnailUrls, setThumbnailUrls] = useState<Record<string, string>>({});
  const [angle, setAngle] = useState("iso");
  const [favorite, setFavorite] = useState(false);
  const [busy, setBusy] = useState<"acquire" | "favorite" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client || !id) return;
    let cancelled = false;
    setListing(null);
    setThumbnailUrls({});
    setError(null);
    void Promise.all([client.getListing(id), client.favoriteListings()])
      .then(async ([item, favorites]) => {
        if (cancelled) return;
        const thumbnails = listingThumbnails(item);
        const preferred = thumbnails.some((thumbnail) => thumbnail.angle === "iso")
          ? "iso"
          : (thumbnails[0]?.angle ?? "iso");
        setListing(item);
        setAngle(preferred);
        setFavorite(favorites.some((candidate) => candidate.id === item.id));
        const entries = await Promise.all(
          thumbnails.map(async (thumbnail) => {
            const download = await client.download(thumbnail.asset_id).catch(() => null);
            return download ? ([thumbnail.angle, download.url] as const) : null;
          }),
        );
        if (!cancelled) {
          setThumbnailUrls(
            Object.fromEntries(
              entries.filter((entry): entry is readonly [string, string] => entry !== null),
            ),
          );
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => { cancelled = true; };
  }, [client, id]);

  const thumbnails = useMemo(() => listing ? listingThumbnails(listing) : [], [listing]);

  async function toggleFavorite() {
    if (!client || !listing || busy) return;
    setBusy("favorite");
    setError(null);
    try {
      if (favorite) await client.removeFavorite(listing.id);
      else await client.addFavorite(listing.id);
      setFavorite((value) => !value);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function actOnListing() {
    if (!client || !session || !listing || busy) return;
    setBusy("acquire");
    setError(null);
    try {
      if (listing.price_cents === 0) {
        const acquired = await client.acquireListing(listing.id, session.workspaceId);
        router.replace(`/project/${acquired.project_id}`);
        return;
      }
      await client.addToCart(listing.id, session.workspaceId);
      router.push("/cart");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBusy(null);
    }
  }

  return (
    <SafeAreaView style={styles.screen} edges={["bottom"]}>
      <Stack.Screen options={{ title: listing?.title ?? "Карточка модели" }} />
      <ScrollView
        style={styles.screen}
        contentContainerStyle={{ width: "100%", maxWidth: 900, alignSelf: "center", padding: 16, paddingBottom: 36, gap: 16 }}
      >
        {!listing && !error ? <Text style={styles.muted}>Загружаем карточку…</Text> : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
        {listing ? (
          <>
            {thumbnailUrls[angle] ? (
              <Image
                accessibilityLabel={`${listing.title}, ракурс ${angle}`}
                source={{ uri: thumbnailUrls[angle] }}
                resizeMode="cover"
                style={{ width: "100%", aspectRatio: 3 / 2, maxHeight: 480, borderRadius: radii.feature, backgroundColor: colors.viewport }}
              />
            ) : (
              <View style={{ width: "100%", aspectRatio: 3 / 2, maxHeight: 480, borderRadius: radii.feature, backgroundColor: colors.viewport, alignItems: "center", justifyContent: "center", gap: 8 }}>
                <CubeIcon color={colors.muted} size={52} strokeWidth={1.2} />
                <Text style={styles.sectionSubtitle}>СОХРАНЁННОЕ ПРЕВЬЮ НЕДОСТУПНО</Text>
              </View>
            )}

            {thumbnails.length > 1 ? (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
                {thumbnails.map((thumbnail) => (
                  <Pressable
                    key={thumbnail.angle}
                    accessibilityRole="radio"
                    accessibilityState={{ checked: angle === thumbnail.angle }}
                    onPress={() => setAngle(thumbnail.angle)}
                    style={{ width: 94, height: 64, borderRadius: radii.control, overflow: "hidden", borderWidth: 2, borderColor: angle === thumbnail.angle ? colors.accent : colors.border, backgroundColor: colors.viewport }}
                  >
                    {thumbnailUrls[thumbnail.angle] ? (
                      <Image source={{ uri: thumbnailUrls[thumbnail.angle] }} resizeMode="cover" style={{ width: "100%", height: "100%" }} />
                    ) : (
                      <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}><Text style={styles.sectionSubtitle}>{thumbnail.angle.toUpperCase()}</Text></View>
                    )}
                  </Pressable>
                ))}
              </ScrollView>
            ) : null}

            <View style={[styles.card, { gap: 12 }]}>
              <View style={{ gap: 4 }}>
                <Text style={styles.title}>{listing.title}</Text>
                <Text style={styles.muted}>@{listing.creator_handle} · {listing.category}</Text>
              </View>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                <View style={[styles.statusBadge, { backgroundColor: colors.accentWashStrong }]}><Text style={[styles.statusText, { color: colors.accent }]}>{listingPrice(listing.price_cents, listing.currency)}</Text></View>
                <View style={styles.statusBadge}><Text style={styles.statusText}>{listing.license_name}</Text></View>
                <View style={styles.statusBadge}><Text style={styles.statusText}>{listing.commercial_use ? "Коммерческое использование" : "Личное использование"}</Text></View>
                {listing.print_ready ? <View style={styles.statusBadge}><Text style={styles.statusText}>Подготовлено к печати</Text></View> : null}
                {listing.editable ? <View style={styles.statusBadge}><Text style={styles.statusText}>Редактируемая модель</Text></View> : null}
              </View>
              {listing.description ? <Text style={{ color: colors.text, lineHeight: 22 }}>{listing.description}</Text> : null}
              {(listing.available_formats ?? []).length > 0 ? (
                <Text style={styles.muted}>Форматы: {(listing.available_formats ?? []).map((format) => format.toUpperCase()).join(", ")}</Text>
              ) : null}
              <Text style={styles.sectionSubtitle}>Скачиваний: {listing.downloads}</Text>
            </View>

            <View style={{ gap: 10 }}>
              <Pressable
                accessibilityRole="button"
                disabled={busy !== null}
                onPress={() => void actOnListing()}
                style={({ pressed }) => [styles.button, styles.buttonPrimary, { opacity: busy || pressed ? 0.7 : 1 }]}
              >
                <Text style={styles.buttonText}>{busy === "acquire" ? (listing.price_cents === 0 ? "Получаем…" : "Добавляем…") : listing.price_cents === 0 ? "Получить модель" : `В корзину · ${listingPrice(listing.price_cents, listing.currency)}`}</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                disabled={busy !== null}
                onPress={() => void toggleFavorite()}
                style={({ pressed }) => [styles.button, { opacity: busy || pressed ? 0.65 : 1 }]}
              >
                <Text style={styles.buttonText}>{busy === "favorite" ? "Сохраняем…" : favorite ? "Убрать из избранного" : "Добавить в избранное"}</Text>
              </Pressable>
            </View>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
