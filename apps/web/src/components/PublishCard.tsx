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
  Version,
} from "@physical-ai/contracts";
import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { CATEGORY_LABELS, CATEGORY_LABELS_RU, price } from "@/components/ListingCard";

export interface PublishCardProps {
  project: Project;
  versions: Version[];
  licences: Licence[];
  listings: Listing[];
  disabled: boolean;
  onPublish: (body: ListingBody) => Promise<void>;
  onWithdraw: (listingId: string, back: boolean) => Promise<void>;
}

export function PublishCard({
  project,
  versions,
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
  const [componentIds, setComponentIds] = useState<string[]>([]);
  const [ru, setRu] = useState(true);
  const current = listings.find((item) => item.version_id === project.head_version_id);
  const componentCandidates = versions.filter(
    (version) => version.id !== project.head_version_id && version.state === "finalized",
  );

  useEffect(() => {
    setRu(navigator.language.toLowerCase().startsWith("ru"));
  }, []);

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
        component_version_ids: componentIds,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card stack">
      <strong>{ru ? "Маркетплейс" : "Marketplace"}</strong>
      {listings.length > 0 && (
        <ul className="list">
          {listings.map((item) => (
            <li key={item.id} className="row" style={{ justifyContent: "space-between" }}>
              <span>
                <Link href={`/market/${item.id}`}>{item.title}</Link>{" "}
                <span className="muted">
                  {price(item, ru ? "ru" : "en")} · {item.status}
                  {item.downloads ? ` · ${ru ? "забрали" : "taken"} ${item.downloads}×` : ""}
                </span>
              </span>
              <button
                className="btn"
                type="button"
                disabled={busy}
                onClick={() => void onWithdraw(item.id, item.status !== "published")}
              >
                {item.status === "published" ? (ru ? "Снять" : "Withdraw") : (ru ? "Вернуть" : "Put back")}
              </button>
            </li>
          ))}
        </ul>
      )}
      {current ? (
        <span className="muted">{ru ? "Текущая версия уже опубликована." : "The current version is on the shelf."}</span>
      ) : (
        <form className="stack" onSubmit={submit}>
          <span className="muted">{ru ? "Опубликуйте текущую сохранённую версию. Покупатель получит копию в своём рабочем пространстве с выбранной лицензией." : "Put the current kept version on the shelf. Buyers get a copy in their own workspace, credited to you under the licence you choose."}</span>
          <input
            className="input"
            placeholder={ru ? "Название" : "Title"}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
          <textarea
            className="textarea"
            placeholder={ru ? "Что это, для чего подходит, как печатать" : "What it is, what it fits, how to print it"}
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
              {Object.entries(ru ? CATEGORY_LABELS_RU : CATEGORY_LABELS).map(([id, label]) => (
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
              placeholder={ru ? "цена, USD" : "price, USD"}
              value={priceText}
              onChange={(event) => setPriceText(event.target.value)}
            />
          </div>
          {componentCandidates.length > 0 && (
            <fieldset className="stack marketplace-components-picker">
              <legend>{ru ? "Добавить версии в набор (необязательно)" : "Add versions to the bundle (optional)"}</legend>
              {componentCandidates.map((version) => (
                <label className="row" key={version.id}>
                  <input
                    type="checkbox"
                    checked={componentIds.includes(version.id)}
                    onChange={(event) => setComponentIds((all) => event.target.checked ? [...all, version.id] : all.filter((id) => id !== version.id))}
                  />
                  {version.label ?? `v${version.sequence_no}`}
                </label>
              ))}
            </fieldset>
          )}
          <input
            className="input"
            placeholder={ru ? "теги через запятую" : "tags, comma separated"}
            value={tags}
            onChange={(event) => setTags(event.target.value)}
          />
          <div className="row">
            <button
              className="btn primary"
              type="submit"
              disabled={disabled || busy || !title.trim()}
            >
              {busy ? (ru ? "Публикую…" : "Publishing…") : (ru ? "Опубликовать" : "Publish")}
            </button>
            <span className="muted" style={{ fontSize: 12 }}>
              {ru ? "0 = бесплатно. Платные товары станут доступны после подключения оплаты." : "0 = free. Priced listings sell once payments are enabled."}
            </span>
          </div>
        </form>
      )}
    </div>
  );
}
