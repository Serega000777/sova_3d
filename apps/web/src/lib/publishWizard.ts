import type { ListingBody, ListingCategory, ListingDomain } from "@physical-ai/contracts";

export const PUBLISH_TITLE_LIMIT = 200;
export const PUBLISH_DESCRIPTION_LIMIT = 5000;
export const PUBLISH_TAG_LIMIT = 12;
export const PUBLISH_COMPONENT_LIMIT = 64;
export const PUBLISH_PRICE_LIMIT_CENTS = 10_000_000;

export interface PublishDraft {
  anchorVersionId: string;
  title: string;
  description: string;
  category: ListingCategory;
  domain: ListingDomain;
  subcategory: string;
  tags: string;
  priceText: string;
  licence: string;
  componentIds: string[];
}

interface PublishComponentCandidate {
  id: string;
  state: string;
  assets: unknown[];
}

export function eligibleAnchorVersions<T extends PublishComponentCandidate>(
  versions: T[],
  publishedVersionIds: string[],
): T[] {
  const published = new Set(publishedVersionIds);
  return versions.filter(
    (version) =>
      version.state === "finalized"
      && version.assets.length > 0
      && !published.has(version.id),
  );
}

export function eligibleComponentVersions<T extends PublishComponentCandidate>(
  versions: T[],
  anchorVersionId: string | null,
): T[] {
  return versions.filter(
    (version) =>
      version.id !== anchorVersionId
      && version.state === "finalized"
      && version.assets.length > 0,
  );
}

export function listingTags(value: string): string[] {
  return value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

export function parsePriceCents(value: string): number | null {
  const normalized = value.trim().replace(",", ".");
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) return null;
  const amount = Number(normalized);
  if (!Number.isFinite(amount) || amount < 0) return null;
  const cents = Math.round(amount * 100);
  return Number.isSafeInteger(cents) && cents <= PUBLISH_PRICE_LIMIT_CENTS ? cents : null;
}

export function buildListingBody(draft: PublishDraft): ListingBody | null {
  const title = draft.title.trim();
  const description = draft.description.trim();
  const tags = listingTags(draft.tags);
  const subcategory = draft.subcategory.trim().toLowerCase();
  const priceCents = parsePriceCents(draft.priceText);
  if (
    !draft.anchorVersionId
    || !title
    || title.length > PUBLISH_TITLE_LIMIT
    || description.length > PUBLISH_DESCRIPTION_LIMIT
    || tags.length > PUBLISH_TAG_LIMIT
    || (subcategory !== "" && !/^[a-z0-9][a-z0-9-]{0,63}$/.test(subcategory))
    || draft.componentIds.length > PUBLISH_COMPONENT_LIMIT
    || priceCents === null
  ) return null;
  return {
    version_id: draft.anchorVersionId,
    title,
    description: description || null,
    category: draft.category,
    domain: draft.domain,
    subcategory: subcategory || null,
    tags,
    price_cents: priceCents,
    currency: "USD",
    license_id: draft.licence,
    component_version_ids: draft.componentIds,
  };
}
