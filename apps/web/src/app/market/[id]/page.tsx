"use client";

/**
 * One listing (F-004): see the model, read the terms, take it into your workspace. A free
 * listing is yours at once; a priced one goes through the payment provider — and says so
 * plainly when none is enabled yet.
 */
import type { Listing } from "@physical-ai/contracts";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { CATEGORY_LABELS, price } from "@/components/ListingCard";
import { useSession } from "@/lib/session";

const ModelViewer = dynamic(
  () => import("@/components/ModelViewer").then((m) => m.ModelViewer),
  { ssr: false },
);

export default function ListingPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { session, ready, client } = useSession();
  const [listing, setListing] = useState<Listing | null>(null);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client) return;
    let cancelled = false;
    client
      .getListing(params.id)
      .then(async (item) => {
        if (cancelled) return;
        setListing(item);
        if (item.model_asset_id) {
          const download = await client.download(item.model_asset_id);
          if (!cancelled) setModelUrl(download.url);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [client, params.id]);

  async function take() {
    if (!client || !session || !listing) return;
    setBusy(true);
    setError(null);
    try {
      const acquired = await client.acquireListing(listing.id, session.workspaceId);
      router.push(`/projects/${acquired.project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!ready) return null;
  if (!session) {
    return (
      <div className="card">
        <p>Sign in to see the listing.</p>
      </div>
    );
  }
  if (!listing) return <div className="muted">{error ?? "Loading…"}</div>;

  const size = listing.summary?.size_mm as number[] | undefined;
  return (
    <div className="project-layout">
      <div className="stack">
        <div>
          <h1 style={{ margin: 0 }}>{listing.title}</h1>
          <span className="muted">
            by <Link href={`/creators/${listing.creator_handle}`}>@{listing.creator_handle}</Link>
            {" · "}
            {CATEGORY_LABELS[listing.category] ?? listing.category}
            {listing.published_at && ` · ${new Date(listing.published_at).toLocaleDateString()}`}
          </span>
        </div>
        <ModelViewer url={modelUrl} selected={[]} onSelect={() => undefined} />
      </div>
      <div className="stack">
        <div className="card stack">
          <div className="row" style={{ flexWrap: "wrap" }}>
            <span className="chip">{price(listing)}</span>
            <span className="chip muted">{listing.license_name}</span>
            {size && (
              <span className="chip mono">{size.map((v) => v.toFixed(0)).join(" × ")} mm</span>
            )}
            {listing.summary?.parametric === true && (
              <span className="chip" title="comes with its operation history: edit it with words">
                parametric
              </span>
            )}
          </div>
          {listing.description && <p style={{ margin: 0 }}>{listing.description}</p>}
          {listing.tags.length > 0 && (
            <div className="row" style={{ flexWrap: "wrap" }}>
              {listing.tags.map((tag) => (
                <span key={tag} className="chip muted">
                  #{tag}
                </span>
              ))}
            </div>
          )}
          <button className="btn primary" type="button" disabled={busy} onClick={() => void take()}>
            {busy
              ? "Taking…"
              : listing.price_cents === 0
                ? "Get it — free"
                : `Buy for ${price(listing)}`}
          </button>
          <span className="muted" style={{ fontSize: 12 }}>
            A copy lands in your workspace as a project of its own, credited to the creator
            under {listing.license_name}.
            {listing.downloads > 0 && ` Taken ${listing.downloads} time(s) so far.`}
          </span>
          {error && <div className="error">{error}</div>}
        </div>
      </div>
    </div>
  );
}
