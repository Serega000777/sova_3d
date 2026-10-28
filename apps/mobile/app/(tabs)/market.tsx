import type { Listing, ListingDomain, MarketplaceFacets } from "@physical-ai/contracts";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Image, Pressable, RefreshControl, ScrollView, Text, TextInput, useWindowDimensions, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { CubeIcon, SearchIcon } from "@/src/AppIcons";
import { listingPrice } from "@/src/projects-screen";
import { useSession } from "@/src/session";
import { colors, elevationLow, radii, styles } from "@/src/theme";

const MARKETPLACE_DOMAINS: ListingDomain[] = ["figure", "element", "house", "yard", "printable", "other"];
const PAGE_SIZE = 24;
type MarketSort = "popular" | "newest" | "cheapest";
type FitEnvelope = { width: number; depth: number; height: number; rotate: boolean };
const SORT_LABELS: Record<MarketSort, string> = {
  popular: "Популярные",
  newest: "Новые",
  cheapest: "Сначала дешевле",
};
const DOMAIN_LABELS: Record<ListingDomain, string> = {
  figure: "Фигуры",
  element: "Элементы",
  house: "Дома",
  yard: "Дворы",
  printable: "Для печати",
  other: "Другое",
};

function verifiedFacets(value: MarketplaceFacets): MarketplaceFacets | null {
  if (
    value.domains.length !== MARKETPLACE_DOMAINS.length ||
    !MARKETPLACE_DOMAINS.every((id) => value.domains.filter((facet) => facet.id === id).length === 1) ||
    !value.domains.every((facet) => (
      Number.isInteger(facet.count) &&
      facet.count >= 0 &&
      new Set(facet.subcategories.map((subcategory) => subcategory.id)).size === facet.subcategories.length &&
      facet.subcategories.every((subcategory) => (
        subcategory.id.length > 0 &&
        subcategory.label_ru.length > 0 &&
        Number.isInteger(subcategory.count) &&
        subcategory.count >= 0
      ))
    ))
  ) return null;
  return value;
}

export default function MarketScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const { client } = useSession();
  const [listings, setListings] = useState<Listing[]>([]);
  const [thumbnailUrls, setThumbnailUrls] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [facets, setFacets] = useState<MarketplaceFacets | null>(null);
  const [selectedDomain, setSelectedDomain] = useState<ListingDomain | null>(null);
  const [selectedSubcategory, setSelectedSubcategory] = useState<string | null>(null);
  const [sort, setSort] = useState<MarketSort>("popular");
  const [freeOnly, setFreeOnly] = useState(false);
  const [bundleOnly, setBundleOnly] = useState(false);
  const [editableOnly, setEditableOnly] = useState(false);
  const [has2dPlanOnly, setHas2dPlanOnly] = useState(false);
  const [printReadyOnly, setPrintReadyOnly] = useState(false);
  const [fitDraft, setFitDraft] = useState({ width: "", depth: "", height: "", rotate: false });
  const [fit, setFit] = useState<FitEnvelope | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [nextOffset, setNextOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const listingRequestId = useRef(0);

  const refresh = useCallback(async () => {
    if (!client) return;
    const requestId = ++listingRequestId.current;
    setRefreshing(true);
    setLoadingMore(false);
    try {
      const next = await client.searchListings({
        q: searchTerm || undefined,
        domain: selectedDomain ?? undefined,
        subcategory: selectedSubcategory ?? undefined,
        free: freeOnly || undefined,
        bundle_only: bundleOnly || undefined,
        editable: editableOnly || undefined,
        has_2d_plan: has2dPlanOnly || undefined,
        print_ready: printReadyOnly || undefined,
        max_width_mm: fit?.width,
        max_depth_mm: fit?.depth,
        max_height_mm: fit?.height,
        rotate_to_fit: fit?.rotate || undefined,
        sort,
        limit: PAGE_SIZE,
        offset: 0,
      });
      if (requestId === listingRequestId.current) {
        setListings(next);
        setHasMore(next.length === PAGE_SIZE);
        setNextOffset(next.length);
        setError(null);
      }
    } catch (err) {
      if (requestId === listingRequestId.current) {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      if (requestId === listingRequestId.current) setRefreshing(false);
    }
  }, [bundleOnly, client, editableOnly, fit, freeOnly, has2dPlanOnly, printReadyOnly, searchTerm, selectedDomain, selectedSubcategory, sort]);

  async function loadMore() {
    if (!client || refreshing || loadingMore || !hasMore) return;
    const requestId = ++listingRequestId.current;
    const offset = nextOffset;
    setLoadingMore(true);
    setError(null);
    try {
      const next = await client.searchListings({
        q: searchTerm || undefined,
        domain: selectedDomain ?? undefined,
        subcategory: selectedSubcategory ?? undefined,
        free: freeOnly || undefined,
        bundle_only: bundleOnly || undefined,
        editable: editableOnly || undefined,
        has_2d_plan: has2dPlanOnly || undefined,
        print_ready: printReadyOnly || undefined,
        max_width_mm: fit?.width,
        max_depth_mm: fit?.depth,
        max_height_mm: fit?.height,
        rotate_to_fit: fit?.rotate || undefined,
        sort,
        limit: PAGE_SIZE,
        offset,
      });
      if (requestId !== listingRequestId.current) return;
      setListings((current) => {
        const seen = new Set(current.map((listing) => listing.id));
        return [...current, ...next.filter((listing) => !seen.has(listing.id))];
      });
      setHasMore(next.length === PAGE_SIZE);
      setNextOffset(offset + next.length);
    } catch (err) {
      if (requestId === listingRequestId.current) {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setLoadingMore(false);
    }
  }

  useFocusEffect(useCallback(() => { void refresh(); }, [refresh]));

  useEffect(() => {
    const timer = setTimeout(() => setSearchTerm(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (!client) return;
    let cancelled = false;
    void client.marketplaceFacets()
      .then((value) => {
        if (!cancelled) setFacets(verifiedFacets(value));
      })
      .catch(() => {
        if (!cancelled) setFacets(null);
      });
    return () => { cancelled = true; };
  }, [client]);

  useEffect(() => {
    let cancelled = false;
    if (!client) {
      setThumbnailUrls({});
      return () => { cancelled = true; };
    }

    void Promise.all(
      listings.map(async (listing) => {
        if (!listing.thumbnail_asset_id) return null;
        const download = await client.download(listing.thumbnail_asset_id).catch(() => null);
        return download ? ([listing.id, download.url] as const) : null;
      }),
    ).then((entries) => {
      if (cancelled) return;
      setThumbnailUrls(
        Object.fromEntries(
          entries.filter((entry): entry is readonly [string, string] => entry !== null),
        ),
      );
    });

    return () => { cancelled = true; };
  }, [client, listings]);

  const contentWidth = Math.min(width - 32, 960);
  const columns = contentWidth >= 760 ? 3 : contentWidth >= 520 ? 2 : 1;
  const cardWidth = (contentWidth - (columns - 1) * 12) / columns;
  const selectedFacet = facets?.domains.find((facet) => facet.id === selectedDomain) ?? null;

  function applyFit() {
    const widthMm = Number(fitDraft.width);
    const depthMm = Number(fitDraft.depth);
    const heightMm = Number(fitDraft.height);
    if (![widthMm, depthMm, heightMm].every((value) => Number.isFinite(value) && value > 0 && value <= 1_000_000)) {
      setError("Укажите три положительных размера не больше 1 000 000 мм.");
      return;
    }
    setError(null);
    setFit({ width: widthMm, depth: depthMm, height: heightMm, rotate: fitDraft.rotate });
  }

  function clearFit() {
    setFitDraft({ width: "", depth: "", height: "", rotate: false });
    setFit(null);
    setError(null);
  }

  return (
    <SafeAreaView style={styles.screen} edges={["top"]}>
      <ScrollView
        style={styles.screen}
        contentContainerStyle={{ width: "100%", maxWidth: 992, alignSelf: "center", padding: 16, paddingBottom: 28, gap: 18 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />}
      >
        <View style={{ flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <View style={{ flex: 1, gap: 5 }}>
            <Text style={[styles.title, { fontSize: 29 }]}>Маркет</Text>
            <Text style={styles.muted}>Модели авторов с указанными ценой и лицензией.</Text>
          </View>
          <View style={{ gap: 8 }}>
            <Pressable accessibilityRole="button" onPress={() => router.push("/market-feed")} style={styles.button}>
              <Text style={styles.buttonText}>Подписки</Text>
            </Pressable>
            <Pressable accessibilityRole="button" onPress={() => router.push("/cart")} style={styles.button}>
              <Text style={styles.buttonText}>Корзина</Text>
            </Pressable>
          </View>
        </View>

        <View style={{ height: 46, borderRadius: radii.control, backgroundColor: colors.panel, borderWidth: 1, borderColor: query ? colors.accent : colors.border, flexDirection: "row", alignItems: "center", paddingHorizontal: 13, gap: 10 }}>
          <SearchIcon color={colors.muted} size={20} />
          <TextInput value={query} onChangeText={setQuery} placeholder="Поиск в маркете" placeholderTextColor={colors.muted} clearButtonMode="while-editing" autoCorrect={false} style={{ flex: 1, color: colors.text, fontSize: 14 }} />
        </View>

        {facets ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            accessibilityRole="tablist"
            contentContainerStyle={{ gap: 8 }}
          >
            <Pressable
              accessibilityRole="tab"
              accessibilityState={{ selected: selectedDomain === null }}
              onPress={() => {
                setSelectedDomain(null);
                setSelectedSubcategory(null);
              }}
              style={[styles.chip, selectedDomain === null && { backgroundColor: colors.accentWashStrong, borderColor: colors.accent }]}
            >
              <Text style={[styles.chipText, selectedDomain === null && { color: colors.accent }]}>Все</Text>
            </Pressable>
            {[...facets.domains]
              .sort((a, b) => a.order - b.order)
              .map((facet) => (
                <Pressable
                  key={facet.id}
                  accessibilityRole="tab"
                  accessibilityState={{ selected: selectedDomain === facet.id && selectedSubcategory === null }}
                  onPress={() => {
                    setSelectedDomain(facet.id);
                    setSelectedSubcategory(null);
                  }}
                  style={[styles.chip, selectedDomain === facet.id && selectedSubcategory === null && { backgroundColor: colors.accentWashStrong, borderColor: colors.accent }]}
                >
                  <Text style={[styles.chipText, selectedDomain === facet.id && selectedSubcategory === null && { color: colors.accent }]}>{DOMAIN_LABELS[facet.id]} · {facet.count}</Text>
                </Pressable>
              ))}
          </ScrollView>
        ) : (
          <Text style={styles.sectionSubtitle}>Категории временно недоступны</Text>
        )}

        {selectedFacet && selectedFacet.subcategories.length > 0 ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            accessibilityRole="tablist"
            contentContainerStyle={{ gap: 8 }}
          >
            {selectedFacet.subcategories
              .slice()
              .sort((a, b) => a.order - b.order)
              .map((subcategory) => (
                <Pressable
                  key={subcategory.id}
                  accessibilityRole="tab"
                  accessibilityState={{ selected: selectedSubcategory === subcategory.id }}
                  onPress={() => setSelectedSubcategory((current) => current === subcategory.id ? null : subcategory.id)}
                  style={[styles.chip, selectedSubcategory === subcategory.id && { backgroundColor: colors.accentWashStrong, borderColor: colors.accent }]}
                >
                  <Text style={[styles.chipText, selectedSubcategory === subcategory.id && { color: colors.accent }]}>{subcategory.label_ru} · {subcategory.count}</Text>
                </Pressable>
              ))}
          </ScrollView>
        ) : null}

        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }} accessibilityRole="radiogroup">
          {(Object.keys(SORT_LABELS) as MarketSort[]).map((item) => (
            <Pressable
              key={item}
              accessibilityRole="radio"
              accessibilityState={{ checked: sort === item }}
              onPress={() => setSort(item)}
              style={[styles.chip, sort === item && { backgroundColor: colors.accentWashStrong, borderColor: colors.accent }]}
            >
              <Text style={[styles.chipText, sort === item && { color: colors.accent }]}>{SORT_LABELS[item]}</Text>
            </Pressable>
          ))}
          <Pressable
            accessibilityRole="switch"
            accessibilityState={{ checked: freeOnly }}
            onPress={() => setFreeOnly((value) => !value)}
            style={[styles.chip, freeOnly && { backgroundColor: colors.accentWashStrong, borderColor: colors.accent }]}
          >
            <Text style={[styles.chipText, freeOnly && { color: colors.accent }]}>Только бесплатные</Text>
          </Pressable>
          <Pressable
            accessibilityRole="switch"
            accessibilityState={{ checked: editableOnly }}
            onPress={() => setEditableOnly((value) => !value)}
            style={[styles.chip, editableOnly && { backgroundColor: colors.accentWashStrong, borderColor: colors.accent }]}
          >
            <Text style={[styles.chipText, editableOnly && { color: colors.accent }]}>Редактируемые</Text>
          </Pressable>
          <Pressable
            accessibilityRole="switch"
            accessibilityState={{ checked: bundleOnly }}
            onPress={() => setBundleOnly((value) => !value)}
            style={[styles.chip, bundleOnly && { backgroundColor: colors.accentWashStrong, borderColor: colors.accent }]}
          >
            <Text style={[styles.chipText, bundleOnly && { color: colors.accent }]}>Только наборы</Text>
          </Pressable>
          <Pressable
            accessibilityRole="switch"
            accessibilityState={{ checked: has2dPlanOnly }}
            onPress={() => setHas2dPlanOnly((value) => !value)}
            style={[styles.chip, has2dPlanOnly && { backgroundColor: colors.accentWashStrong, borderColor: colors.accent }]}
          >
            <Text style={[styles.chipText, has2dPlanOnly && { color: colors.accent }]}>С 2D-планом</Text>
          </Pressable>
          <Pressable
            accessibilityRole="switch"
            accessibilityState={{ checked: printReadyOnly }}
            onPress={() => setPrintReadyOnly((value) => !value)}
            style={[styles.chip, printReadyOnly && { backgroundColor: colors.accentWashStrong, borderColor: colors.accent }]}
          >
            <Text style={[styles.chipText, printReadyOnly && { color: colors.accent }]}>Готовы к печати</Text>
          </Pressable>
        </View>

        <View style={[styles.card, { gap: 10 }]}>
          <Text style={styles.heading}>Поместится в габариты, мм</Text>
          <Text style={styles.sectionSubtitle}>Каталог проверит только модели с измеренной геометрией.</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
            {(["width", "depth", "height"] as const).map((dimension) => (
              <TextInput
                key={dimension}
                accessibilityLabel={{ width: "Максимальная ширина, мм", depth: "Максимальная глубина, мм", height: "Максимальная высота, мм" }[dimension]}
                value={fitDraft[dimension]}
                onChangeText={(value) => setFitDraft((current) => ({ ...current, [dimension]: value }))}
                keyboardType="decimal-pad"
                placeholder={{ width: "Ширина", depth: "Глубина", height: "Высота" }[dimension]}
                placeholderTextColor={colors.muted}
                style={[styles.input, { flexGrow: 1, minWidth: 96 }]}
              />
            ))}
          </View>
          <Pressable
            accessibilityRole="switch"
            accessibilityState={{ checked: fitDraft.rotate }}
            onPress={() => setFitDraft((current) => ({ ...current, rotate: !current.rotate }))}
            style={[styles.chip, { alignSelf: "flex-start" }, fitDraft.rotate && { backgroundColor: colors.accentWashStrong, borderColor: colors.accent }]}
          >
            <Text style={[styles.chipText, fitDraft.rotate && { color: colors.accent }]}>Разрешить поворот</Text>
          </Pressable>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
            <Pressable accessibilityRole="button" onPress={applyFit} style={[styles.button, styles.buttonPrimary]}>
              <Text style={styles.buttonText}>Применить габариты</Text>
            </Pressable>
            {fit ? (
              <Pressable accessibilityRole="button" onPress={clearFit} style={styles.button}>
                <Text style={styles.buttonText}>Сбросить габариты</Text>
              </Pressable>
            ) : null}
          </View>
        </View>

        {error && <Text style={styles.error}>{error}</Text>}

        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 12 }}>
          {listings.map((listing) => (
            <View key={listing.id} style={{ width: cardWidth, borderRadius: radii.feature, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.panel, overflow: "hidden", ...elevationLow }}>
              {thumbnailUrls[listing.id] ? (
                <Image
                  accessibilityLabel={`Превью ${listing.title}`}
                  source={{ uri: thumbnailUrls[listing.id] }}
                  resizeMode="cover"
                  style={{ width: "100%", height: 150, backgroundColor: colors.viewport }}
                />
              ) : (
                <View accessibilityLabel="Изображение товара не передано маркетплейсом" style={{ height: 150, backgroundColor: colors.viewport, alignItems: "center", justifyContent: "center", gap: 8 }}>
                  <CubeIcon color={colors.muted} size={42} strokeWidth={1.2} />
                  <Text style={styles.sectionSubtitle}>ПРЕВЬЮ НЕДОСТУПНО</Text>
                </View>
              )}
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
                  accessibilityLabel={`Открыть карточку ${listing.title}`}
                  onPress={() => router.push(`/market/${listing.id}`)}
                  style={({ pressed }) => [styles.button, styles.buttonPrimary, { opacity: pressed ? 0.78 : 1 }]}
                >
                  <Text style={styles.buttonText}>Подробнее</Text>
                </Pressable>
              </View>
            </View>
          ))}
        </View>

        {hasMore && listings.length > 0 ? (
          <Pressable
            accessibilityRole="button"
            disabled={refreshing || loadingMore}
            onPress={() => void loadMore()}
            style={[styles.button, (refreshing || loadingMore) && { opacity: 0.5 }]}
          >
            <Text style={styles.buttonText}>{loadingMore ? "Загружаем…" : "Показать ещё"}</Text>
          </Pressable>
        ) : null}

        {!refreshing && listings.length === 0 && (
          <View style={{ minHeight: 150, alignItems: "center", justifyContent: "center", gap: 6 }}>
            <Text style={styles.heading}>{query ? "Ничего не найдено" : "В маркете пока нет моделей"}</Text>
            <Text style={styles.sectionSubtitle}>{query ? "Попробуйте другой запрос" : "Потяните экран вниз, чтобы обновить"}</Text>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
