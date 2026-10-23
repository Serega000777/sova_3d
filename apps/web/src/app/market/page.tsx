"use client";

/**
 * Marketplace (T-149, F-004/F-065): the shelf. Search by words, narrow by category or
 * free-only, or by measured installation envelope (F-046), or read the feed of the creators
 * you follow. Your own creator profile — the
 * handle your listings are credited to — is edited here too.
 */
import type { CreatorProfile, Listing, ListingCategory } from "@physical-ai/contracts";
import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { CATEGORY_LABELS, CATEGORY_LABELS_RU, ListingCard } from "@/components/ListingCard";
import { LoadingScreen } from "@/components/LoadingScreen";
import { useSession } from "@/lib/session";

const CATEGORIES = Object.keys(CATEGORY_LABELS) as ListingCategory[];

type Language = "en" | "ru";

const T = {
  en: {
    signIn: "Sign in to browse the marketplace.",
    title: "Marketplace",
    tabs: { all: "everything", feed: "creators I follow", mine: "my listings" },
    search: "cable clip, phone stand, bracket…",
    sort: { newest: "newest", popular: "most taken", cheapest: "cheapest" },
    freeOnly: "free only",
    empty: {
      feed: "Follow a creator and their new listings show up here.",
      mine: "Nothing listed yet — open a project and publish a kept version.",
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
  },
  ru: {
    signIn: "Войдите, чтобы открыть маркетплейс.",
    title: "Маркетплейс",
    tabs: { all: "всё", feed: "авторы, на которых я подписан", mine: "мои публикации" },
    search: "зажим для кабеля, подставка для телефона, кронштейн…",
    sort: { newest: "сначала новые", popular: "самые популярные", cheapest: "сначала дешёвые" },
    freeOnly: "только бесплатные",
    empty: {
      feed: "Подпишитесь на автора — его новые публикации появятся здесь.",
      mine: "Публикаций пока нет — откройте проект и опубликуйте сохранённую версию.",
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
  },
} as const;

export default function MarketPage() {
  const { session, ready, client } = useSession();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<ListingCategory | null>(null);
  const [free, setFree] = useState(false);
  const [sort, setSort] = useState<"newest" | "popular" | "cheapest">("newest");
  const [fitDraft, setFitDraft] = useState({ width: "", depth: "", height: "", rotate: false });
  const [fit, setFit] = useState<{ width: number; depth: number; height: number; rotate: boolean } | null>(null);
  const [view, setView] = useState<"all" | "feed" | "mine">("all");
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [listings, setListings] = useState<Listing[]>([]);
  const [showcase, setShowcase] = useState<{ newest: Listing[]; popular: Listing[] }>({
    newest: [],
    popular: [],
  });
  const [profile, setProfile] = useState<CreatorProfile | null>(null);
  const [draft, setDraft] = useState({ handle: "", display_name: "", bio: "" });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [language, setLanguage] = useState<Language>("ru");
  const t = T[language];

  useEffect(() => {
    setLanguage(navigator.language.toLowerCase().startsWith("ru") ? "ru" : "en");
  }, []);

  const refresh = useCallback(async () => {
    if (!client) return;
    setError(null);
    try {
      if (view === "feed") setListings(await client.marketplaceFeed());
      else if (view === "mine") setListings(await client.myListings());
      else {
        setListings(
          await client.searchListings({
            q: q.trim() || undefined,
            category: category ?? undefined,
            free: free || undefined,
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
  }, [client, view, q, category, free, fit, sort]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

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

  if (!ready) return <LoadingScreen />;
  if (!session) {
    return (
      <div className="card">
        <p>{t.signIn}</p>
      </div>
    );
  }

  return (
    <div className="stack">
      <div className="card stack">
        <div className="row" style={{ flexWrap: "wrap" }}>
          <strong>{t.title}</strong>
          {(["all", "feed", "mine"] as const).map((tab) => (
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
                <option value="newest">{t.sort.newest}</option>
                <option value="popular">{t.sort.popular}</option>
                <option value="cheapest">{t.sort.cheapest}</option>
              </select>
              <label className="row muted" style={{ gap: 6 }}>
                <input type="checkbox" checked={free} onChange={(e) => setFree(e.target.checked)} />
                {t.freeOnly}
              </label>
            </div>
            <div className="row" style={{ flexWrap: "wrap" }}>
              {CATEGORIES.map((id) => (
                <button
                  key={id}
                  type="button"
                  className={`chip ${category === id ? "selected" : ""}`}
                  onClick={() => setCategory(category === id ? null : id)}
                >
                  {(language === "ru" ? CATEGORY_LABELS_RU : CATEGORY_LABELS)[id]}
                </button>
              ))}
            </div>
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
            <Link className="btn" href="/cart">{t.cart}</Link>
          </div>
        </div>
        {notice && <span className="muted">{notice}</span>}
      </div>

      {view === "all" && !q.trim() && category === null && !free && (
        <div className="marketplace-showcase stack">
          {([
            ["newest", t.newestLane, showcase.newest],
            ["popular", t.popularLane, showcase.popular],
          ] as const).map(([id, title, items]) => items.length > 0 && (
            <section key={id} className="stack" aria-labelledby={`marketplace-${id}-heading`}>
              <h2 id={`marketplace-${id}-heading`}>{title}</h2>
              <div className="marketplace-lane">
                {items.map((listing) => (
                  <ListingCard key={`${id}-${listing.id}`} listing={listing} language={language} />
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
    </div>
  );
}
