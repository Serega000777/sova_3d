"use client";

/**
 * Publish to the marketplace (T-149, F-004): the project's current kept version goes on
 * the shelf under a licence, free or priced. What is already listed shows with its state.
 */
import type {
  Licence,
  Listing,
  ListingBody,
  ListingCategory,
  Project,
} from "@physical-ai/contracts";
import Link from "next/link";
import { type FormEvent, useState } from "react";

import { CATEGORY_LABELS, price } from "@/components/ListingCard";

export interface PublishCardProps {
  project: Project;
  licences: Licence[];
  listings: Listing[];
  disabled: boolean;
  onPublish: (body: ListingBody) => Promise<void>;
  onWithdraw: (listingId: string, back: boolean) => Promise<void>;
}

export function PublishCard({
  project,
  licences,
  listings,
  disabled,
  onPublish,
  onWithdraw,
}: PublishCardProps) {
  const [title, setTitle] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [category, setCategory] = useState<ListingCategory>("print");
  const [tags, setTags] = useState("");
  const [priceText, setPriceText] = useState("0");
  const [licence, setLicence] = useState(project.license_id ?? "CC-BY-4.0");
  const [busy, setBusy] = useState(false);
  const current = listings.find((item) => item.version_id === project.head_version_id);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await onPublish({
        version_id: null,
        title: title.trim(),
        description: description.trim() || null,
        category,
        tags: tags
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
        price_cents: Math.round(Number(priceText.replace(",", ".")) * 100) || 0,
        currency: "USD",
        license_id: licence,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card stack">
      <strong>Marketplace</strong>
      {listings.length > 0 && (
        <ul className="list">
          {listings.map((item) => (
            <li key={item.id} className="row" style={{ justifyContent: "space-between" }}>
              <span>
                <Link href={`/market/${item.id}`}>{item.title}</Link>{" "}
                <span className="muted">
                  {price(item)} · {item.status}
                  {item.downloads ? ` · taken ${item.downloads}×` : ""}
                </span>
              </span>
              <button
                className="btn"
                type="button"
                disabled={busy}
                onClick={() => void onWithdraw(item.id, item.status !== "published")}
              >
                {item.status === "published" ? "Withdraw" : "Put back"}
              </button>
            </li>
          ))}
        </ul>
      )}
      {current ? (
        <span className="muted">The current version is on the shelf.</span>
      ) : (
        <form className="stack" onSubmit={submit}>
          <span className="muted">
            Put the current kept version on the shelf. Buyers get a copy in their own
            workspace, credited to you under the licence you choose.
          </span>
          <input
            className="input"
            placeholder="Title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
          <textarea
            className="textarea"
            placeholder="What it is, what it fits, how to print it"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
          <div className="row" style={{ flexWrap: "wrap" }}>
            <select
              className="input"
              style={{ maxWidth: 150 }}
              value={category}
              onChange={(event) => setCategory(event.target.value as ListingCategory)}
            >
              {Object.entries(CATEGORY_LABELS).map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
            <select
              className="input"
              style={{ maxWidth: 220 }}
              value={licence}
              onChange={(event) => setLicence(event.target.value)}
            >
              {licences.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <input
              className="input"
              style={{ maxWidth: 120 }}
              placeholder="price, USD"
              value={priceText}
              onChange={(event) => setPriceText(event.target.value)}
            />
          </div>
          <input
            className="input"
            placeholder="tags, comma separated"
            value={tags}
            onChange={(event) => setTags(event.target.value)}
          />
          <div className="row">
            <button
              className="btn primary"
              type="submit"
              disabled={disabled || busy || !title.trim()}
            >
              {busy ? "Publishing…" : "Publish"}
            </button>
            <span className="muted" style={{ fontSize: 12 }}>
              0 = free. Priced listings sell once payments are enabled.
            </span>
          </div>
        </form>
      )}
    </div>
  );
}
