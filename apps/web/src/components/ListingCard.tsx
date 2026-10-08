"use client";

/** One listing on the shelf (F-004): what it is, who made it, what it costs, its terms. */
import type { Listing } from "@physical-ai/contracts";
import Link from "next/link";

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

export function ListingCard({ listing, language = "en" }: { listing: Listing; language?: Language }) {
  const size = listing.summary?.size_mm as number[] | undefined;
  const categories = language === "ru" ? CATEGORY_LABELS_RU : CATEGORY_LABELS;
  return (
    <div className="card stack" style={{ gap: 6 }}>
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
        {size && <span className="chip mono">{size.map((v) => v.toFixed(0)).join(" × ")} mm</span>}
        {listing.downloads > 0 && (
          <span className="muted" style={{ fontSize: 12 }}>
            {language === "ru" ? "забрали" : "taken"} {listing.downloads}×
          </span>
        )}
      </div>
    </div>
  );
}
