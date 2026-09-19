"use client";

/**
 * Marketplace (T-149, F-004/F-065): the shelf. Search by words, narrow by category or
 * free-only, or read the feed of the creators you follow. Your own creator profile — the
 * handle your listings are credited to — is edited here too.
 */
import type { CreatorProfile, Listing, ListingCategory } from "@physical-ai/contracts";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { CATEGORY_LABELS, ListingCard } from "@/components/ListingCard";
import { useSession } from "@/lib/session";

const CATEGORIES = Object.keys(CATEGORY_LABELS) as ListingCategory[];

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
      setNotice(`Your listings are credited to @${me.handle}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (!ready) return null;
  if (!session) {
    return (
      <div className="card">
        <p>Sign in to browse the marketplace.</p>
      </div>
    );
  }

  return (
    <div className="stack">
      <div className="card stack">
        <div className="row" style={{ flexWrap: "wrap" }}>
          <strong>Marketplace</strong>
          {(["all", "feed", "mine"] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              className={`chip ${view === tab ? "selected" : ""}`}
              onClick={() => setView(tab)}
            >
              {tab === "all" ? "everything" : tab === "feed" ? "creators I follow" : "my listings"}
            </button>
          ))}
        </div>
        {view === "all" && (
          <>
            <div className="row" style={{ flexWrap: "wrap" }}>
              <input
                className="input"
                style={{ maxWidth: 320 }}
                placeholder="cable clip, phone stand, bracket…"
                value={q}
                onChange={(event) => setQ(event.target.value)}
              />
              <select
                className="input"
                style={{ maxWidth: 150 }}
                value={sort}
                onChange={(event) => setSort(event.target.value as typeof sort)}
              >
                <option value="newest">newest</option>
                <option value="popular">most taken</option>
                <option value="cheapest">cheapest</option>
              </select>
              <label className="row muted" style={{ gap: 6 }}>
                <input type="checkbox" checked={free} onChange={(e) => setFree(e.target.checked)} />
                free only
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
                  {CATEGORY_LABELS[id]}
                </button>
              ))}
            </div>
          </>
        )}
        {error && <div className="error">{error}</div>}
      </div>

      <div className="grid projects">
        {listings.map((listing) => (
          <ListingCard key={listing.id} listing={listing} />
        ))}
        {listings.length === 0 && (
          <div className="muted">
            {view === "feed"
              ? "Follow a creator and their new listings show up here."
              : view === "mine"
                ? "Nothing listed yet — open a project and publish a kept version."
                : "Nothing on the shelf matches. Publish something from a project."}
          </div>
        )}
      </div>

      <form className="card stack" onSubmit={saveProfile}>
        <strong>Your creator profile</strong>
        <span className="muted">
          Listings are credited to your handle; people can follow it.
          {profile ? ` ${profile.followers} follower(s), ${profile.listings} listing(s).` : ""}
        </span>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <input
            className="input"
            style={{ maxWidth: 200 }}
            placeholder="handle"
            value={draft.handle}
            onChange={(event) => setDraft({ ...draft, handle: event.target.value })}
          />
          <input
            className="input"
            style={{ maxWidth: 240 }}
            placeholder="display name"
            value={draft.display_name}
            onChange={(event) => setDraft({ ...draft, display_name: event.target.value })}
          />
        </div>
        <textarea
          className="textarea"
          placeholder="a few words about what you make"
          value={draft.bio}
          onChange={(event) => setDraft({ ...draft, bio: event.target.value })}
        />
        <div className="row">
          <button className="btn primary" type="submit">
            Save profile
          </button>
          {notice && <span className="muted">{notice}</span>}
        </div>
      </form>
    </div>
  );
}
