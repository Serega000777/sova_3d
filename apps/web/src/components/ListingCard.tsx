"use client";

/** One listing on the shelf (F-004): what it is, who made it, what it costs, its terms. */
import type { Listing } from "@physical-ai/contracts";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useSession } from "@/lib/session";

export const CATEGORY_LABELS: Record<string, string> = {
  print: "3D printing",
  game: "Games",
  arvr: "AR / VR",
  cad: "CAD",
  other: "Other",
};

export const CATEGORY_LABELS_RU: Record<string, string> = {
  print: "3D-печать",
  game: "Игры",
  arvr: "AR / VR",
  cad: "CAD",
  other: "Другое",
};

type Language = "en" | "ru";

export function price(listing: Listing, language: Language = "en"): string {
  if (listing.price_cents === 0) return language === "ru" ? "Бесплатно" : "Free";
  return `${(listing.price_cents / 100).toFixed(2)} ${listing.currency}`;
}

export function PrintBadge({ listing, language }: { listing: Listing; language: Language }) {
  const badge = listing.print_verified;
  if (!badge) return null;
  const text = badge.status === "green"
    ? language === "ru" ? "✓ Проверено на печать" : "✓ Print verified"
    : badge.status === "yellow"
      ? language === "ru" ? "Требует настройки печати" : "Print setup needed"
      : language === "ru" ? "Не прошла проверку" : "Print check failed";
  return (
    <span className={`chip status-${badge.status}`} title={`${badge.score.toFixed(0)}/100`}>
      {text}
    </span>
  );
}

export function ListingCard({
  listing,
  language = "en",
  onAddToCart,
  layout = "grid",
  variant = "default",
}: {
  listing: Listing;
  language?: Language;
  onAddToCart?: (listing: Listing) => Promise<void>;
  layout?: "grid" | "list";
  variant?: "default" | "featured" | "lane";
}) {
  const { client } = useSession();
  const [adding, setAdding] = useState(false);
  const [thumbnailUrl, setThumbnailUrl] = useState<string | null>(null);
  const size = listing.summary?.size_mm as number[] | undefined;
  const components = listing.components ?? [];
  const categories = language === "ru" ? CATEGORY_LABELS_RU : CATEGORY_LABELS;
  useEffect(() => {
    let cancelled = false;
    setThumbnailUrl(null);
    if (!client || !listing.thumbnail_asset_id) return () => { cancelled = true; };
    void client.download(listing.thumbnail_asset_id).then((download) => {
      if (!cancelled) setThumbnailUrl(download.url);
    }).catch(() => {
      if (!cancelled) setThumbnailUrl(null);
    });
    return () => { cancelled = true; };
  }, [client, listing.thumbnail_asset_id]);
  async function add() {
    if (!onAddToCart) return;
    setAdding(true);
    try {
      await onAddToCart(listing);
    } finally {
      setAdding(false);
    }
  }
  return (
    <article className={`card stack marketplace-card marketplace-card-${variant} ${layout === "list" ? "marketplace-card-list" : ""}`}>
      <Link className="marketplace-card-image" href={`/market/${listing.id}`}>
        {thumbnailUrl ? (
          <img src={thumbnailUrl} alt={listing.title} />
        ) : (
          <span aria-hidden="true">SOVA 3D</span>
        )}
      </Link>
      <Link href={`/market/${listing.id}`}>
        <strong>{listing.title}</strong>
      </Link>
      <span className="muted">
        {language === "ru" ? "автор" : "by"}{" "}
        <Link href={`/creators/${listing.creator_handle}`}>@{listing.creator_handle}</Link>
        {" · "}
        {categories[listing.category] ?? listing.category}
      </span>
      {listing.description && (
        <span className="muted" style={{ fontSize: 13 }}>
          {listing.description.length > 140
            ? `${listing.description.slice(0, 140)}…`
            : listing.description}
        </span>
      )}
      <div className="row" style={{ flexWrap: "wrap" }}>
        <span className="chip">{price(listing, language)}</span>
        <span className="chip muted">{listing.license_name}</span>
        <PrintBadge listing={listing} language={language} />
        {(listing.available_formats ?? []).slice(0, 3).map((format) => (
          <span className="chip mono" key={format}>{format.toUpperCase()}</span>
        ))}
        {listing.editable && (
          <span className="chip">{language === "ru" ? "Редактируемая" : "Editable"}</span>
        )}
        {listing.has_2d_plan && <span className="chip">{language === "ru" ? "2D-план" : "2D plan"}</span>}
        {listing.print_ready && (
          <span className="chip status-green">
            {language === "ru" ? "Готово к печати" : "Print ready"}
          </span>
        )}
        {listing.is_bundle && (
          <span className="chip">
            {language === "ru" ? `Набор: ${components.length + 1}` : `Bundle: ${components.length + 1}`}
          </span>
        )}
        {size && <span className="chip mono">{size.map((v) => v.toFixed(0)).join(" × ")} mm</span>}
        {listing.house && <>
          <span className="chip">{listing.house.gross_floor_area_m2.toFixed(1)} m²</span>
          <span className="chip">{listing.house.floors} {language === "ru" ? "эт." : "floors"}</span>
          <span className="chip">
            {{ rectangle: language === "ru" ? "Прямоугольный" : "Rectangle", l_shape: language === "ru" ? "Г-образный" : "L-shaped", t_shape: language === "ru" ? "Т-образный" : "T-shaped" }[listing.house.shape]}
          </span>
        </>}
        {listing.downloads > 0 && (
          <span className="muted" style={{ fontSize: 12 }}>
            {language === "ru" ? "забрали" : "taken"} {listing.downloads}×
          </span>
        )}
      </div>
      {onAddToCart && (
        <button className="btn primary" type="button" disabled={adding} onClick={() => void add()}>
          {adding
            ? language === "ru" ? "Добавляю…" : "Adding…"
            : language === "ru" ? "В корзину" : "Add to cart"}
        </button>
      )}
    </article>
  );
}
