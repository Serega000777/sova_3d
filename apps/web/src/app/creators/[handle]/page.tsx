"use client";

/** A creator's page (F-065): who they are, what they listed, and a Follow button. */
import type { CreatorPage } from "@physical-ai/contracts";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ListingCard } from "@/components/ListingCard";
import { useSession } from "@/lib/session";

export default function CreatorPageView() {
  const params = useParams<{ handle: string }>();
  const { session, ready, client } = useSession();
  const [page, setPage] = useState<CreatorPage | null>(null);
  const [myHandle, setMyHandle] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client) return;
    try {
      setPage(await client.creatorPage(params.handle));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [client, params.handle]);

  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    if (!client) return;
    void client
      .myCreatorProfile()
      .then((me) => setMyHandle(me.handle))
      .catch(() => setMyHandle(null));
  }, [client]);

  async function toggleFollow() {
    if (!client || !page) return;
    setError(null);
    try {
      if (page.profile.following) await client.unfollowCreator(page.profile.handle);
      else await client.followCreator(page.profile.handle);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (!ready) return null;
  if (!session) {
    return (
      <div className="card">
        <p>Sign in to see creators.</p>
      </div>
    );
  }
  if (!page) return <div className="muted">{error ?? "Loading…"}</div>;

  const own = myHandle !== null && page.profile.handle === myHandle;
  return (
    <div className="stack">
      <div className="card stack">
        <div className="row" style={{ flexWrap: "wrap", justifyContent: "space-between" }}>
          <div>
            <h1 style={{ margin: 0 }}>{page.profile.display_name}</h1>
            <span className="muted">
              @{page.profile.handle} · {page.profile.followers} follower(s) ·{" "}
              {page.profile.listings} listing(s)
            </span>
          </div>
          {!own && (
            <button
              className={`btn ${page.profile.following ? "" : "primary"}`}
              type="button"
              onClick={() => void toggleFollow()}
            >
              {page.profile.following ? "Following ✓" : "Follow"}
            </button>
          )}
        </div>
        {page.profile.bio && <p style={{ margin: 0 }}>{page.profile.bio}</p>}
        {error && <div className="error">{error}</div>}
      </div>
      <div className="grid projects">
        {page.listings.map((listing) => (
          <ListingCard key={listing.id} listing={listing} />
        ))}
        {page.listings.length === 0 && <div className="muted">Nothing listed yet.</div>}
      </div>
    </div>
  );
}
