"use client";

/**
 * Marketplace (T-149, F-004/F-065): the shelf. Search by words, narrow by category or
 * free-only, or read the feed of the creators you follow. Your own creator profile — the
 * handle your listings are credited to — is edited here too.
 */
import type { CreatorProfile, Listing, ListingCategory } from "@physical-ai/contracts";
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
  },
} as const;

export default function MarketPage() {
  const { session, ready, client } = useSession();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<ListingCategory | null>(null);
  const [free, setFree] = useState(false);
  const [sort, setSort] = useState<"newest" | "popular" | "cheapest">("newest");
  const [view, setView] = useState<"all" | "feed" | "mine">("all");
  const [listings, setListings] = useState<Listing[]>([]);
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
            sort,
          }),
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [client, view, q, category, free, sort]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

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
          </>
        )}
        {error && <div className="error">{error}</div>}
      </div>

      <div className="grid projects">
        {listings.map((listing) => (
          <ListingCard key={listing.id} listing={listing} language={language} />
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
