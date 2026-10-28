import type { Listing } from "@physical-ai/contracts";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { Image, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { CubeIcon } from "@/src/AppIcons";
import { MarketplaceFloorPlans } from "@/src/MarketplaceFloorPlans";
import { MarketplaceSiteCompatibility } from "@/src/MarketplaceSiteCompatibility";
import { MarketplaceSitePlan } from "@/src/MarketplaceSitePlan";
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
  const [componentThumbnailUrls, setComponentThumbnailUrls] = useState<Record<string, string>>({});
  const [angle, setAngle] = useState("iso");
  const [favorite, setFavorite] = useState(false);
  const [inCart, setInCart] = useState(false);
  const [busy, setBusy] = useState<"acquire" | "favorite" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client || !id) return;
    let cancelled = false;
    setListing(null);
    setThumbnailUrls({});
    setComponentThumbnailUrls({});
    setError(null);
    void Promise.all([
      client.getListing(id),
      client.favoriteListings(),
      session ? client.getCart(session.workspaceId) : Promise.resolve(null),
    ])
      .then(async ([item, favorites, cart]) => {
        if (cancelled) return;
        const thumbnails = listingThumbnails(item);
        const preferred = thumbnails.some((thumbnail) => thumbnail.angle === "iso")
          ? "iso"
          : (thumbnails[0]?.angle ?? "iso");
        setListing(item);
        setAngle(preferred);
        setFavorite(favorites.some((candidate) => candidate.id === item.id));
        setInCart(cart?.items.some((candidate) => candidate.id === item.id) ?? false);
        const [entries, componentEntries] = await Promise.all([
          Promise.all(
            thumbnails.map(async (thumbnail) => {
              const download = await client.download(thumbnail.asset_id).catch(() => null);
              return download ? ([thumbnail.angle, download.url] as const) : null;
            }),
          ),
          Promise.all(
            (item.components ?? []).map(async (component) => {
              if (!component.thumbnail_asset_id) return null;
              const download = await client.download(component.thumbnail_asset_id).catch(() => null);
              return download ? ([component.id, download.url] as const) : null;
            }),
          ),
        ]);
        if (!cancelled) {
          setThumbnailUrls(
            Object.fromEntries(
              entries.filter((entry): entry is readonly [string, string] => entry !== null),
            ),
          );
          setComponentThumbnailUrls(
            Object.fromEntries(
              componentEntries.filter((entry): entry is readonly [string, string] => entry !== null),
            ),
          );
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => { cancelled = true; };
  }, [client, id, session]);

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
      if (inCart) {
        router.push("/cart");
        setBusy(null);
        return;
      }
      await client.addToCart(listing.id, session.workspaceId);
      setInCart(true);
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
                <Pressable accessibilityRole="link" onPress={() => router.push(`/creator/${encodeURIComponent(listing.creator_handle)}`)}>
                  <Text style={[styles.muted, { color: colors.accent }]}>@{listing.creator_handle} · {listing.category}</Text>
                </Pressable>
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

            {listing.house ? (
              <View style={[styles.card, { gap: 10 }]}>
                <Text style={styles.heading}>Параметры дома</Text>
                <Text style={styles.sectionSubtitle}>Метрики подтверждены опубликованной неизменяемой версией.</Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                  <View style={styles.chip}><Text style={styles.chipText}>{listing.house.gross_floor_area_m2.toFixed(1)} м²</Text></View>
                  <View style={styles.chip}><Text style={styles.chipText}>{listing.house.floors} эт.</Text></View>
                  <View style={styles.chip}><Text style={styles.chipText}>{{ rectangle: "Прямоугольный", l_shape: "Г-образный", t_shape: "Т-образный" }[listing.house.shape]}</Text></View>
                  <View style={styles.chip}><Text style={styles.chipText}>{(listing.house.length_mm / 1000).toFixed(1)} × {(listing.house.width_mm / 1000).toFixed(1)} м</Text></View>
                </View>
                {listing.house.rooms.length > 0 ? (
                  <View style={{ gap: 8 }}>
                    <Text style={styles.heading}>Помещения по плану</Text>
                    {listing.house.rooms.map((room, index) => (
                      <View key={`${room.floor_index}-${room.kind}-${index}`} style={[styles.row, { justifyContent: "space-between", gap: 8 }]}>
                        <View style={{ flex: 1 }}>
                          <Text style={styles.heading}>{room.name}</Text>
                          <Text style={styles.sectionSubtitle}>Этаж {room.floor_index + 1}</Text>
                        </View>
                        <Text style={styles.heading}>{room.area_m2.toFixed(1)} м²</Text>
                      </View>
                    ))}
                  </View>
                ) : null}
              </View>
            ) : null}

            {listing.floor_plans.length > 0 ? <MarketplaceFloorPlans levels={listing.floor_plans} /> : null}

            {listing.site_plan ? <MarketplaceSitePlan site={listing.site_plan} /> : null}

            {listing.site_plan && client && session ? <MarketplaceSiteCompatibility client={client} workspaceId={session.workspaceId} listingId={listing.id} /> : null}

            {(listing.components ?? []).length > 0 ? (
              <View style={[styles.card, { gap: 10 }]}>
                <Text style={styles.heading}>Состав набора · {(listing.components ?? []).length + 1}</Text>
                <Text style={styles.sectionSubtitle}>Показаны только сохранённые сервером модули и превью.</Text>
                <View style={{ gap: 8 }}>
                  <View style={[styles.row, { alignItems: "center", gap: 10 }]}>
                    <View style={{ width: 72, height: 54, borderRadius: radii.control, overflow: "hidden", backgroundColor: colors.viewport }}>
                      {thumbnailUrls[angle] ? (
                        <Image source={{ uri: thumbnailUrls[angle] }} resizeMode="cover" style={{ width: "100%", height: "100%" }} />
                      ) : (
                        <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}><CubeIcon color={colors.muted} size={24} /></View>
                      )}
                    </View>
                    <View style={{ flex: 1, gap: 2 }}>
                      <Text style={styles.heading}>1. {listing.title}</Text>
                      <Text style={styles.sectionSubtitle}>Основная модель</Text>
                    </View>
                  </View>
                  {(listing.components ?? []).map((component, index) => (
                    <View key={component.id} style={[styles.row, { alignItems: "center", gap: 10 }]}>
                      <View style={{ width: 72, height: 54, borderRadius: radii.control, overflow: "hidden", backgroundColor: colors.viewport }}>
                        {componentThumbnailUrls[component.id] ? (
                          <Image source={{ uri: componentThumbnailUrls[component.id] }} resizeMode="cover" style={{ width: "100%", height: "100%" }} />
                        ) : (
                          <View accessibilityLabel="Сохранённое превью компонента недоступно" style={{ flex: 1, alignItems: "center", justifyContent: "center" }}><CubeIcon color={colors.muted} size={24} /></View>
                        )}
                      </View>
                      <View style={{ flex: 1, gap: 2 }}>
                        <Text style={styles.heading}>{index + 2}. {component.label}</Text>
                        {component.print_verified?.status === "green" ? <Text style={[styles.sectionSubtitle, { color: colors.green }]}>Печать проверена</Text> : null}
                      </View>
                    </View>
                  ))}
                </View>
              </View>
            ) : null}

            <View style={{ gap: 10 }}>
              <Pressable
                accessibilityRole="button"
                disabled={busy !== null}
                onPress={() => void actOnListing()}
                style={({ pressed }) => [styles.button, styles.buttonPrimary, { opacity: busy || pressed ? 0.7 : 1 }]}
              >
                <Text style={styles.buttonText}>{busy === "acquire" ? (listing.price_cents === 0 ? "Получаем…" : inCart ? "Открываем…" : "Добавляем…") : listing.price_cents === 0 ? "Получить модель" : inCart ? "Открыть корзину" : `В корзину · ${listingPrice(listing.price_cents, listing.currency)}`}</Text>
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
