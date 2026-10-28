"use client";

/**
 * Marketplace (T-149, F-004/F-065): the shelf. Search by words, narrow by category or
 * free-only, or by measured installation envelope (F-046), or read the feed of the creators
 * you follow. Your own creator profile — the
 * handle your listings are credited to — is edited here too.
 */
import type {
  CreatorProfile,
  Listing,
  ListingCategory,
  ListingDomain,
  MarketplaceFacets,
  Project,
  Template,
} from "@physical-ai/contracts";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { CATEGORY_LABELS, CATEGORY_LABELS_RU, ListingCard } from "@/components/ListingCard";
import { LoadingScreen } from "@/components/LoadingScreen";
import { TemplateGallery } from "@/components/TemplateGallery";
import { useSession } from "@/lib/session";
import { projectEnvelope, type ProjectEnvelope } from "@/lib/project-envelope";

const CATEGORIES = Object.keys(CATEGORY_LABELS) as ListingCategory[];
const DOMAINS: ListingDomain[] = ["figure", "element", "house", "yard", "printable", "other"];
const DOMAIN_LABELS: Record<ListingDomain, { en: string; ru: string; icon: string }> = {
  figure: { en: "Figures", ru: "Фигуры", icon: "◇" },
  element: { en: "Elements", ru: "Элементы", icon: "⌑" },
  house: { en: "Houses", ru: "Дома", icon: "▱" },
  yard: { en: "Yards", ru: "Дворы", icon: "⌗" },
  printable: { en: "For printing", ru: "Для печати", icon: "⬡" },
  other: { en: "Other", ru: "Другое", icon: "＋" },
};

type Language = "en" | "ru";

const T = {
  en: {
    signIn: "Sign in to browse the marketplace.",
    title: "Marketplace",
    tabs: { all: "everything", favorites: "favorites", feed: "creators I follow", mine: "my listings" },
    search: "cable clip, phone stand, bracket…",
    sort: { relevant: "most relevant", newest: "newest", popular: "most taken", cheapest: "cheapest" },
    freeOnly: "free only",
    bundleOnly: "bundles only",
    format: "file format",
    editable: "editable feature tree",
    hasPlan: "includes a 2D plan",
    printReady: "print check passed",
    price: "Price ($)",
    priceMin: "min",
    priceMax: "max",
    applyPrice: "Apply price",
    clearPrice: "Clear",
    empty: {
      feed: "Follow a creator and their new listings show up here.",
      mine: "Nothing listed yet — open a project and publish a kept version.",
      favorites: "Save a listing and it will appear here.",
      all: "Nothing on the shelf matches. Publish something from a project.",
    },
    profile: "Your creator profile",
    profileNote: "Listings are credited to your handle; people can follow it.",
    profileStats: (followers: number, listings: number) => `${followers} follower(s), ${listings} listing(s).`,
    handle: "handle",
    displayName: "display name",
    bio: "a few words about what you make",
    save: "Save profile",
    credited: (handle: string) => `Your listings are credited to @${handle}`,
    results: (count: number) => `${count} result${count === 1 ? "" : "s"}`,
    grid: "Grid",
    list: "List",
    cart: "Cart",
    added: "Added to cart",
    newestLane: "New arrivals",
    popularLane: "Popular",
    fit: "Fits inside (mm)",
    width: "width",
    depth: "depth",
    height: "height",
    rotate: "allow rotation",
    applyFit: "Check fit",
    clearFit: "Clear",
    designers: "Verified specialist templates",
    designersNote: "Choose a niche, set exact dimensions, and start a buildable CAD project.",
    business: "Build a measured product line",
    browse: "Browse categories",
    allCategories: "All models",
    featured: "Popular now",
    featuredNote: "A real listing ranked by completed acquisitions — no invented recommendation.",
    projectFitLane: "By project envelope",
    projectFitNote: "A size-only shortlist from the saved valid head bounding box — not a recommendation, installation proof or collision check.",
    projectFitUnavailable: "The selected project has no valid saved 3D envelope.",
    project: "Project",
    catalogue: "Catalogue",
    filters: "Filters",
    closeFilters: "Close filters",
    useCategory: "Use / format",
  },
  ru: {
    signIn: "Войдите, чтобы открыть маркетплейс.",
    title: "Маркетплейс",
    tabs: { all: "всё", favorites: "избранное", feed: "авторы, на которых я подписан", mine: "мои публикации" },
    search: "зажим для кабеля, подставка для телефона, кронштейн…",
    sort: { relevant: "по релевантности", newest: "сначала новые", popular: "самые популярные", cheapest: "сначала дешёвые" },
    freeOnly: "только бесплатные",
    bundleOnly: "только комплекты",
    format: "формат файла",
    editable: "редактируемая история",
    hasPlan: "есть 2D-план",
    printReady: "проверено для печати",
    price: "Цена ($)",
    priceMin: "от",
    priceMax: "до",
    applyPrice: "Применить цену",
    clearPrice: "Сбросить",
    empty: {
      feed: "Подпишитесь на автора — его новые публикации появятся здесь.",
      mine: "Публикаций пока нет — откройте проект и опубликуйте сохранённую версию.",
      favorites: "Сохраните товар — он появится здесь.",
      all: "Ничего подходящего не найдено. Опубликуйте модель из проекта.",
    },
    profile: "Ваш профиль автора",
    profileNote: "Публикации подписываются вашим именем автора; люди могут на него подписаться.",
    profileStats: (followers: number, listings: number) => `${followers} подписчиков, ${listings} публикаций.`,
    handle: "имя автора",
    displayName: "отображаемое имя",
    bio: "несколько слов о том, что вы создаёте",
    save: "Сохранить профиль",
    credited: (handle: string) => `Ваши публикации подписаны именем @${handle}`,
    results: (count: number) => `${count} результатов`,
    grid: "Сетка",
    list: "Список",
    cart: "Корзина",
    added: "Добавлено в корзину",
    newestLane: "Новые",
    popularLane: "Популярные",
    fit: "Помещается в габарит (мм)",
    width: "ширина",
    depth: "глубина",
    height: "высота",
    rotate: "можно повернуть",
    applyFit: "Проверить посадку",
    clearFit: "Сбросить",
    designers: "Проверенные специализированные шаблоны",
    designersNote: "Выберите нишу, задайте точные размеры и запустите собираемый CAD-проект.",
    business: "Собрать линейку с измеренной себестоимостью",
    browse: "Разделы каталога",
    allCategories: "Все модели",
    featured: "Сейчас популярно",
    featuredNote: "Реальный товар по числу получений — без выдуманной рекомендации.",
    projectFitLane: "По габариту проекта",
    projectFitNote: "Это размерный shortlist по сохранённому валидному bounding box head‑версии, а не рекомендация, доказательство монтажа или проверка коллизий.",
    projectFitUnavailable: "У выбранного проекта нет валидного сохранённого 3D‑габарита.",
    project: "Проект",
    catalogue: "Каталог",
    filters: "Фильтры",
    closeFilters: "Закрыть фильтры",
    useCategory: "Назначение / формат",
  },
} as const;

export default function MarketPage() {
  const router = useRouter();
  const { session, ready, client } = useSession();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<ListingCategory | null>(null);
  const [domain, setDomain] = useState<ListingDomain | null>(null);
  const [subcategory, setSubcategory] = useState<string | null>(null);
  const [facets, setFacets] = useState<MarketplaceFacets>({ domains: [] });
  const [free, setFree] = useState(false);
  const [bundleOnly, setBundleOnly] = useState(false);
  const [formatId, setFormatId] = useState("");
  const [capabilities, setCapabilities] = useState({
    editable: false,
    hasPlan: false,
    printReady: false,
  });
  const [priceDraft, setPriceDraft] = useState({ min: "", max: "" });
  const [price, setPrice] = useState<{ min?: number; max?: number } | null>(null);
  const [sort, setSort] = useState<"relevant" | "newest" | "popular" | "cheapest">("relevant");
  const [fitDraft, setFitDraft] = useState({ width: "", depth: "", height: "", rotate: false });
  const [fit, setFit] = useState<{ width: number; depth: number; height: number; rotate: boolean } | null>(null);
  const [view, setView] = useState<"all" | "favorites" | "feed" | "mine">("all");
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [listings, setListings] = useState<Listing[]>([]);
  const [showcase, setShowcase] = useState<{ newest: Listing[]; popular: Listing[] }>({
    newest: [],
    popular: [],
  });
  const [projects, setProjects] = useState<Project[]>([]);
  const [fitProjectId, setFitProjectId] = useState("");
  const [projectFit, setProjectFit] = useState<{ envelope: ProjectEnvelope; listings: Listing[] } | null>(null);
  const [profile, setProfile] = useState<CreatorProfile | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [startingTemplate, setStartingTemplate] = useState(false);
  const [draft, setDraft] = useState({ handle: "", display_name: "", bio: "" });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [language, setLanguage] = useState<Language>("ru");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const t = T[language];
  const categoryLabels = language === "ru" ? CATEGORY_LABELS_RU : CATEGORY_LABELS;

  useEffect(() => {
    setLanguage(navigator.language.toLowerCase().startsWith("ru") ? "ru" : "en");
  }, []);

  const refresh = useCallback(async () => {
    if (!client) return;
    setError(null);
    try {
      if (view === "feed") setListings(await client.marketplaceFeed());
      else if (view === "mine") setListings(await client.myListings());
      else if (view === "favorites") setListings(await client.favoriteListings());
      else {
        setListings(
          await client.searchListings({
            q: q.trim() || undefined,
            category: category ?? undefined,
            domain: domain ?? undefined,
            subcategory: subcategory ?? undefined,
            free: free || undefined,
            min_price_cents: price?.min,
            max_price_cents: price?.max,
            bundle_only: bundleOnly || undefined,
            format: formatId || undefined,
            editable: capabilities.editable || undefined,
            has_2d_plan: capabilities.hasPlan || undefined,
            print_ready: capabilities.printReady || undefined,
            max_width_mm: fit?.width,
            max_depth_mm: fit?.depth,
            max_height_mm: fit?.height,
            rotate_to_fit: fit?.rotate || undefined,
            sort,
          }),
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [client, view, q, category, domain, subcategory, free, price, bundleOnly, formatId, capabilities, fit, sort]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!client) return;
    void client.marketplaceFacets().then(setFacets).catch(() => setFacets({ domains: [] }));
  }, [client]);

  useEffect(() => {
    if (!client || !session) return;
    let cancelled = false;
    void client.listProjects(session.workspaceId).then((rows) => {
      if (cancelled) return;
      const candidates = rows.filter((project) => project.head_version_id);
      setProjects(candidates);
      setFitProjectId((current) => current || candidates[0]?.id || "");
    }).catch(() => {
      if (!cancelled) setProjects([]);
    });
    return () => { cancelled = true; };
  }, [client, session]);

  useEffect(() => {
    if (!client || !fitProjectId) {
      setProjectFit(null);
      return;
    }
    let cancelled = false;
    setProjectFit(null);
    void client.getProject(fitProjectId).then(async (project) => {
      const envelope = projectEnvelope(project);
      if (!envelope) {
        if (!cancelled) setProjectFit(null);
        return;
      }
      const listings = await client.searchListings({
        max_width_mm: envelope[0],
        max_depth_mm: envelope[1],
        max_height_mm: envelope[2],
        rotate_to_fit: true,
        sort: "newest",
        limit: 6,
      });
      if (!cancelled) setProjectFit({ envelope, listings });
    }).catch(() => {
      if (!cancelled) setProjectFit(null);
    });
    return () => { cancelled = true; };
  }, [client, fitProjectId]);

  useEffect(() => {
    if (!client) return;
    let cancelled = false;
    void Promise.all([
      client.searchListings({ sort: "newest", limit: 6 }),
      client.searchListings({ sort: "popular", limit: 6 }),
    ]).then(([newest, popular]) => {
      if (!cancelled) setShowcase({ newest, popular });
    }).catch(() => {
      if (!cancelled) setShowcase({ newest: [], popular: [] });
    });
    return () => { cancelled = true; };
  }, [client]);

  useEffect(() => {
    if (!client) return;
    void client.listTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, [client]);

  useEffect(() => {
    if (!client) return;
    void client
      .myCreatorProfile()
      .then((me) => {
        setProfile(me);
        setDraft({ handle: me.handle, display_name: me.display_name, bio: me.bio ?? "" });
      })
      .catch(() => setProfile(null));
  }, [client]);

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    if (!client) return;
    setError(null);
    try {
      const me = await client.updateCreatorProfile({
        handle: draft.handle.trim() || null,
        display_name: draft.display_name.trim() || null,
        bio: draft.bio,
        website: null,
      });
      setProfile(me);
      setNotice(t.credited(me.handle));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function addToCart(listing: Listing) {
    if (!client || !session) return;
    setError(null);
    try {
      await client.addToCart(listing.id, session.workspaceId);
      setNotice(`${t.added}: ${listing.title}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function startTemplate(template: Template, params: Record<string, number>) {
    if (!client || !session) return;
    setError(null);
    setStartingTemplate(true);
    try {
      const started = await client.startFromTemplate({
        workspace_id: session.workspaceId,
        template_id: template.id,
        params,
        language,
      });
      router.push(`/projects/${started.project_id}?template=${template.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setStartingTemplate(false);
    }
  }

  function applyFit(event: FormEvent) {
    event.preventDefault();
    const width = Number(fitDraft.width);
    const depth = Number(fitDraft.depth);
    const height = Number(fitDraft.height);
    if (![width, depth, height].every((value) => Number.isFinite(value) && value > 0)) {
      setError(language === "ru" ? "Укажите три положительных размера в миллиметрах." : "Enter three positive dimensions in millimetres.");
      return;
    }
    setError(null);
    setFit({ width, depth, height, rotate: fitDraft.rotate });
  }

  function applyPrice(event: FormEvent) {
    event.preventDefault();
    const min = priceDraft.min === "" ? undefined : Number(priceDraft.min);
    const max = priceDraft.max === "" ? undefined : Number(priceDraft.max);
    if (
      (min !== undefined && (!Number.isFinite(min) || min < 0))
      || (max !== undefined && (!Number.isFinite(max) || max < 0))
      || (min !== undefined && max !== undefined && min > max)
    ) {
      setError(language === "ru" ? "Укажите корректный диапазон цены." : "Enter a valid price range.");
      return;
    }
    setError(null);
    if (min === undefined && max === undefined) {
      setPrice(null);
      return;
    }
    setPrice({
      min: min === undefined ? undefined : Math.round(min * 100),
      max: max === undefined ? undefined : Math.round(max * 100),
    });
  }

  function selectCategory(next: ListingCategory | null) {
    setView("all");
    setCategory(next);
  }

  function selectDomain(next: ListingDomain | null) {
    setView("all");
    setDomain(next);
    setSubcategory(null);
  }

  if (!ready) return <LoadingScreen />;
  if (!session) {
    return (
      <div className="card">
        <p>{t.signIn}</p>
      </div>
    );
  }

  const featured = showcase.popular[0] ?? showcase.newest[0] ?? null;
  const showEditorial = view === "all" && !q.trim() && category === null && domain === null
    && subcategory === null && !free && !bundleOnly && price === null && fit === null;
  const domainFacets = DOMAINS.map((id) =>
    facets.domains.find((facet) => facet.id === id) ?? { id, count: 0, subcategories: [] },
  );

  return (
    <div className="stack marketplace-page">
      <header className="marketplace-head row">
        <div>
          <span className="marketplace-kicker">SOVA 3D</span>
          <h1>{t.title}</h1>
        </div>
        <div className="row marketplace-head-actions">
          <Link className="btn" href="/business">{t.business}</Link>
          <Link className="btn primary" href="/cart">{t.cart}</Link>
        </div>
      </header>

      {showEditorial && featured && (
        <section className="marketplace-featured" aria-labelledby="marketplace-featured-heading">
          <div className="marketplace-featured-copy">
            <span className="marketplace-kicker">{t.featured}</span>
            <h2 id="marketplace-featured-heading">{featured.title}</h2>
            <p>{t.featuredNote}</p>
            <Link className="btn primary" href={`/market/${featured.id}`}>
              {language === "ru" ? "Открыть товар" : "Open listing"}
            </Link>
          </div>
          <ListingCard
            listing={featured}
            language={language}
            variant="featured"
            onAddToCart={addToCart}
          />
        </section>
      )}

      <div className="marketplace-catalog-layout">
        <aside className="marketplace-category-rail" aria-label={t.browse}>
          <strong>{t.browse}</strong>
          <button
            type="button"
            className={domain === null ? "active" : ""}
            onClick={() => selectDomain(null)}
          >
            <span aria-hidden="true">◫</span>
            <span className="marketplace-facet-label">
              {t.allCategories}<small>{domainFacets.reduce((sum, facet) => sum + facet.count, 0)}</small>
            </span>
          </button>
          {domainFacets.map((facet) => (
            <div className="marketplace-facet-group" key={facet.id}>
              <button
                type="button"
                className={domain === facet.id && subcategory === null ? "active" : ""}
                onClick={() => selectDomain(domain === facet.id ? null : facet.id)}
              >
                <span aria-hidden="true">{DOMAIN_LABELS[facet.id].icon}</span>
                <span className="marketplace-facet-label">
                  {DOMAIN_LABELS[facet.id][language]}<small>{facet.count}</small>
                </span>
              </button>
              {domain === facet.id && facet.subcategories.map((child) => (
                <button
                  key={child.id}
                  type="button"
                  className={`marketplace-subcategory ${subcategory === child.id ? "active" : ""}`}
                  onClick={() => setSubcategory(subcategory === child.id ? null : child.id)}
                >
                  <span aria-hidden="true">·</span>
                  <span className="marketplace-facet-label">
                    {language === "ru" ? child.label_ru : child.label_en}<small>{child.count}</small>
                  </span>
                </button>
              ))}
            </div>
          ))}
        </aside>

        <main className="stack marketplace-catalog">
          <div className={`card stack marketplace-filters ${filtersOpen ? "mobile-open" : ""}`}>
            <div className="row" style={{ flexWrap: "wrap" }}>
              <strong>{t.catalogue}</strong>
              <div className="row marketplace-desktop-tabs">
                {(["all", "favorites", "feed", "mine"] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    className={`chip ${view === tab ? "selected" : ""}`}
                    onClick={() => setView(tab)}
                  >
                    {t.tabs[tab]}
                  </button>
                ))}
              </div>
              <button
                type="button"
                className="marketplace-filter-close"
                onClick={() => setFiltersOpen(false)}
              >
                {t.closeFilters} ×
              </button>
            </div>
            {view === "all" && (
              <>
                <div className="row" style={{ flexWrap: "wrap" }}>
                  <input
                    className="input"
                    style={{ maxWidth: 320 }}
                    placeholder={t.search}
                    value={q}
                    onChange={(event) => setQ(event.target.value)}
                  />
                  <select
                    className="input"
                    style={{ maxWidth: 150 }}
                    value={sort}
                    onChange={(event) => setSort(event.target.value as typeof sort)}
                  >
                    <option value="relevant">{t.sort.relevant}</option>
                    <option value="newest">{t.sort.newest}</option>
                    <option value="popular">{t.sort.popular}</option>
                    <option value="cheapest">{t.sort.cheapest}</option>
                  </select>
                  <label className="row muted" style={{ gap: 6 }}>
                    <input type="checkbox" checked={free} onChange={(e) => setFree(e.target.checked)} />
                    {t.freeOnly}
                  </label>
                  <label className="row muted" style={{ gap: 6 }}>
                    <input
                      type="checkbox"
                      checked={bundleOnly}
                      onChange={(event) => setBundleOnly(event.target.checked)}
                    />
                    {t.bundleOnly}
                  </label>
                  <select
                    className="input"
                    style={{ maxWidth: 160 }}
                    aria-label={t.format}
                    value={formatId}
                    onChange={(event) => setFormatId(event.target.value)}
                  >
                    <option value="">{t.format}</option>
                    {["stl", "3mf", "step", "brep", "glb", "gltf", "obj", "ply"].map((format) => (
                      <option key={format} value={format}>{format.toUpperCase()}</option>
                    ))}
                  </select>
                  {([
                    ["editable", t.editable],
                    ["hasPlan", t.hasPlan],
                    ["printReady", t.printReady],
                  ] as const).map(([key, label]) => (
                    <label className="row muted" style={{ gap: 6 }} key={key}>
                      <input
                        type="checkbox"
                        checked={capabilities[key]}
                        onChange={(event) => setCapabilities({
                          ...capabilities,
                          [key]: event.target.checked,
                        })}
                      />
                      {label}
                    </label>
                  ))}
                </div>
                <div className="marketplace-mobile-categories">
                  {domainFacets.map((facet) => (
                    <button
                      key={facet.id}
                      type="button"
                      className={`chip ${domain === facet.id ? "selected" : ""}`}
                      onClick={() => selectDomain(domain === facet.id ? null : facet.id)}
                    >
                      {DOMAIN_LABELS[facet.id][language]} · {facet.count}
                    </button>
                  ))}
                  {domainFacets.find((facet) => facet.id === domain)?.subcategories.map((child) => (
                    <button
                      key={child.id}
                      type="button"
                      className={`chip ${subcategory === child.id ? "selected" : ""}`}
                      onClick={() => setSubcategory(subcategory === child.id ? null : child.id)}
                    >
                      {language === "ru" ? child.label_ru : child.label_en} · {child.count}
                    </button>
                  ))}
                </div>
                <div className="marketplace-mobile-categories">
                  <span className="muted">{t.useCategory}</span>
                  {CATEGORIES.map((id) => (
                    <button
                      key={id}
                      type="button"
                      className={`chip ${category === id ? "selected" : ""}`}
                      onClick={() => selectCategory(category === id ? null : id)}
                    >
                      {categoryLabels[id]}
                    </button>
                  ))}
                </div>
                <form className="row" style={{ flexWrap: "wrap" }} onSubmit={applyPrice}>
                  <span className="muted">{t.price}</span>
                  {(["min", "max"] as const).map((bound) => (
                    <input
                      key={bound}
                      className="input"
                      style={{ maxWidth: 110 }}
                      type="number"
                      min="0"
                      max="100000"
                      step="0.01"
                      inputMode="decimal"
                      aria-label={`${t.price}: ${t[bound === "min" ? "priceMin" : "priceMax"]}`}
                      placeholder={t[bound === "min" ? "priceMin" : "priceMax"]}
                      value={priceDraft[bound]}
                      onChange={(event) => setPriceDraft({ ...priceDraft, [bound]: event.target.value })}
                    />
                  ))}
                  <button className="chip" type="submit">{t.applyPrice}</button>
                  {price && (
                    <button
                      className="chip"
                      type="button"
                      onClick={() => {
                        setPrice(null);
                        setPriceDraft({ min: "", max: "" });
                      }}
                    >
                      {t.clearPrice}
                    </button>
                  )}
                </form>
                <form className="row" style={{ flexWrap: "wrap" }} onSubmit={applyFit}>
                  <span className="muted">{t.fit}</span>
                  {(["width", "depth", "height"] as const).map((axis) => (
                    <input
                      key={axis}
                      className="input"
                      style={{ maxWidth: 110 }}
                      type="number"
                      min="0.01"
                      max="1000000"
                      step="any"
                      inputMode="decimal"
                      aria-label={`${t.fit}: ${t[axis]}`}
                      placeholder={t[axis]}
                      value={fitDraft[axis]}
                      onChange={(event) => setFitDraft({ ...fitDraft, [axis]: event.target.value })}
                    />
                  ))}
                  <label className="row muted" style={{ gap: 6 }}>
                    <input
                      type="checkbox"
                      checked={fitDraft.rotate}
                      onChange={(event) => setFitDraft({ ...fitDraft, rotate: event.target.checked })}
                    />
                    {t.rotate}
                  </label>
                  <button className="chip" type="submit">{t.applyFit}</button>
                  {fit && (
                    <button
                      className="chip"
                      type="button"
                      onClick={() => {
                        setFit(null);
                        setFitDraft({ width: "", depth: "", height: "", rotate: false });
                      }}
                    >
                      {t.clearFit}
                    </button>
                  )}
                </form>
              </>
            )}
            {error && <div className="error">{error}</div>}
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>{t.results(listings.length)}</strong>
              <div className="row">
                <button
                  className={`chip ${layout === "grid" ? "selected" : ""}`}
                  type="button"
                  onClick={() => setLayout("grid")}
                >
                  ▦ {t.grid}
                </button>
                <button
                  className={`chip ${layout === "list" ? "selected" : ""}`}
                  type="button"
                  onClick={() => setLayout("list")}
                >
                  ☰ {t.list}
                </button>
              </div>
            </div>
            {notice && <span className="muted">{notice}</span>}
          </div>

          {showEditorial && (
            <div className="marketplace-showcase stack">
              {projects.length > 0 && (
                <section className="stack" aria-labelledby="marketplace-project-fit-heading">
                  <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
                    <div>
                      <h2 id="marketplace-project-fit-heading">{t.projectFitLane}</h2>
                      <p className="muted">{t.projectFitNote}</p>
                    </div>
                    <label className="row muted">
                      {t.project}
                      <select className="input" value={fitProjectId} onChange={(event) => setFitProjectId(event.target.value)}>
                        {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
                      </select>
                    </label>
                  </div>
                  {projectFit ? (
                    <>
                      <span className="mono muted">{projectFit.envelope.map((value) => value.toFixed(0)).join(" × ")} mm</span>
                      <div className="marketplace-lane">
                        {projectFit.listings.map((listing) => (
                          <ListingCard
                            key={`project-fit-${listing.id}`}
                            listing={listing}
                            language={language}
                            variant="lane"
                            onAddToCart={addToCart}
                          />
                        ))}
                      </div>
                    </>
                  ) : (
                    <span className="muted">{t.projectFitUnavailable}</span>
                  )}
                </section>
              )}
              {([
                ["newest", t.newestLane, showcase.newest],
                ["popular", t.popularLane, showcase.popular],
              ] as const).map(([id, title, items]) => items.length > 0 && (
                <section key={id} className="stack" aria-labelledby={`marketplace-${id}-heading`}>
                  <h2 id={`marketplace-${id}-heading`}>{title}</h2>
                  <div className="marketplace-lane">
                    {items.map((listing) => (
                      <ListingCard
                        key={`${id}-${listing.id}`}
                        listing={listing}
                        language={language}
                        variant="lane"
                        onAddToCart={addToCart}
                      />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}

          <div className={layout === "grid" ? "grid projects marketplace-grid" : "stack marketplace-list"}>
            {listings.map((listing) => (
              <ListingCard
                key={listing.id}
                listing={listing}
                language={language}
                layout={layout}
                onAddToCart={addToCart}
              />
            ))}
            {listings.length === 0 && (
              <div className="muted">
                {t.empty[view]}
              </div>
            )}
          </div>
        </main>
      </div>

      {view === "all" && (
        <section className="card stack" aria-label={t.designers}>
          <TemplateGallery
            templates={templates}
            language={language}
            disabled={startingTemplate}
            onStart={startTemplate}
            heading={t.designers}
            description={t.designersNote}
            filterByCategory
          />
        </section>
      )}

      <form className="card stack" onSubmit={saveProfile}>
        <strong>{t.profile}</strong>
        <span className="muted">
          {t.profileNote}
          {profile ? ` ${t.profileStats(profile.followers, profile.listings)}` : ""}
        </span>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <input
            className="input"
            style={{ maxWidth: 200 }}
            placeholder={t.handle}
            value={draft.handle}
            onChange={(event) => setDraft({ ...draft, handle: event.target.value })}
          />
          <input
            className="input"
            style={{ maxWidth: 240 }}
            placeholder={t.displayName}
            value={draft.display_name}
            onChange={(event) => setDraft({ ...draft, display_name: event.target.value })}
          />
        </div>
        <textarea
          className="textarea"
          placeholder={t.bio}
          value={draft.bio}
          onChange={(event) => setDraft({ ...draft, bio: event.target.value })}
        />
        <div className="row">
          <button className="btn primary" type="submit">
            {t.save}
          </button>
          {notice && <span className="muted">{notice}</span>}
        </div>
      </form>

      <nav className="marketplace-mobile-nav" aria-label={t.title}>
        {(["all", "feed", "mine"] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            className={view === tab ? "active" : ""}
            onClick={() => setView(tab)}
          >
            <span aria-hidden="true">{tab === "all" ? "◫" : tab === "feed" ? "☆" : "○"}</span>
            {t.tabs[tab]}
          </button>
        ))}
        <button
          type="button"
          aria-expanded={filtersOpen}
          className={filtersOpen ? "active" : ""}
          onClick={() => {
            if (!filtersOpen) setView("all");
            setFiltersOpen((open) => !open);
          }}
        >
          <span aria-hidden="true">≡</span>{t.filters}
        </button>
        <Link href="/cart"><span aria-hidden="true">▣</span>{t.cart}</Link>
      </nav>
    </div>
  );
}
