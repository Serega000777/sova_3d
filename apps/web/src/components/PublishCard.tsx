"use client";

/** Publish the current kept version through a bounded four-step marketplace flow. */
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
import {
  buildListingBody,
  listingTags,
  parsePriceCents,
  PUBLISH_COMPONENT_LIMIT,
  PUBLISH_DESCRIPTION_LIMIT,
  PUBLISH_TAG_LIMIT,
  PUBLISH_TITLE_LIMIT,
} from "@/lib/publishWizard";

export interface PublishCardProps {
  project: Project;
  versions: Version[];
  licences: Licence[];
  listings: Listing[];
  disabled: boolean;
  onPublish: (body: ListingBody) => Promise<void>;
  onWithdraw: (listingId: string, back: boolean) => Promise<void>;
}

const STEP_IDS = ["files", "description", "rights", "review"] as const;

export function PublishCard({
  project,
  versions,
  licences,
  listings,
  disabled,
  onPublish,
  onWithdraw,
}: PublishCardProps) {
  const [step, setStep] = useState(0);
  const [title, setTitle] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [category, setCategory] = useState<ListingCategory>("print");
  const [tags, setTags] = useState("");
  const [priceText, setPriceText] = useState("0");
  const [licence, setLicence] = useState(project.license_id ?? "CC-BY-4.0");
  const [busy, setBusy] = useState(false);
  const [componentIds, setComponentIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [ru, setRu] = useState(true);
  const current = listings.find((item) => item.version_id === project.head_version_id);
  const anchorVersion = versions.find((version) => version.id === project.head_version_id);
  const componentCandidates = versions.filter(
    (version) => version.id !== project.head_version_id && version.state === "finalized",
  );
  const tagList = listingTags(tags);
  const parsedPrice = parsePriceCents(priceText);
  const categories = ru ? CATEGORY_LABELS_RU : CATEGORY_LABELS;
  const selectedLicence = licences.find((item) => item.id === licence);
  const steps = ru
    ? ["Файлы", "Описание", "Цена и права", "Проверка"]
    : ["Files", "Description", "Price & rights", "Review"];

  useEffect(() => {
    setRu(navigator.language.toLowerCase().startsWith("ru"));
  }, []);

  function validateCurrentStep(): boolean {
    if (step === 1 && !title.trim()) {
      setError(ru ? "Добавьте название, чтобы продолжить." : "Add a title to continue.");
      return false;
    }
    if (step === 1 && tagList.length > PUBLISH_TAG_LIMIT) {
      setError(
        ru
          ? `Можно указать не больше ${PUBLISH_TAG_LIMIT} тегов.`
          : `Use no more than ${PUBLISH_TAG_LIMIT} tags.`,
      );
      return false;
    }
    if (step === 2 && parsedPrice === null) {
      setError(
        ru
          ? "Укажите корректную неотрицательную цену. Для бесплатной работы введите 0."
          : "Enter a valid non-negative price. Use 0 for a free listing.",
      );
      return false;
    }
    setError(null);
    return true;
  }

  function next() {
    if (!validateCurrentStep()) return;
    setStep((value) => Math.min(value + 1, STEP_IDS.length - 1));
  }

  function back() {
    setError(null);
    setStep((value) => Math.max(value - 1, 0));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (step !== STEP_IDS.length - 1) {
      next();
      return;
    }
    const body = buildListingBody({
      title,
      description,
      category,
      tags,
      priceText,
      licence,
      componentIds,
    });
    if (!body || tagList.length > PUBLISH_TAG_LIMIT) {
      setError(
        ru
          ? "Проверьте название, теги и неотрицательную цену."
          : "Check the title, tags, and non-negative price.",
      );
      return;
    }
    setBusy(true);
    try {
      await onPublish(body);
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
                {item.status === "published"
                  ? ru ? "Снять" : "Withdraw"
                  : ru ? "Вернуть" : "Put back"}
              </button>
            </li>
          ))}
        </ul>
      )}
      {current ? (
        <span className="muted">
          {ru ? "Текущая версия уже опубликована." : "The current version is on the shelf."}
        </span>
      ) : (
        <form className="stack marketplace-publish-wizard" onSubmit={submit}>
          <ol className="marketplace-publish-steps" aria-label={ru ? "Шаги публикации" : "Publishing steps"}>
            {steps.map((label, index) => (
              <li
                key={STEP_IDS[index]}
                className={index === step ? "active" : index < step ? "complete" : ""}
                aria-current={index === step ? "step" : undefined}
              >
                <span>{index + 1}</span>{label}
              </li>
            ))}
          </ol>

          {step === 0 && (
            <section className="stack" aria-labelledby="publish-files-heading">
              <strong id="publish-files-heading">{steps[0]}</strong>
              <span className="muted">
                {ru
                  ? "Публикуется текущая сохранённая версия проекта. Загрузка дополнительных форматов в этом сценарии не выполняется."
                  : "This flow publishes the project's current kept version. It does not upload additional formats."}
              </span>
              <div className="marketplace-publish-file row">
                <span aria-hidden="true">◆</span>
                <span>
                  <strong>{anchorVersion?.label ?? project.name}</strong>
                  <small className="muted">
                    {ru ? "Основная версия" : "Primary version"}
                  </small>
                </span>
              </div>
              {componentCandidates.length > 0 && (
                <fieldset className="stack marketplace-components-picker">
                  <legend>
                    {ru ? "Добавить версии в набор (необязательно)" : "Add versions to the bundle (optional)"}
                  </legend>
                  {componentCandidates.map((version) => (
                    <label className="row" key={version.id}>
                      <input
                        type="checkbox"
                        checked={componentIds.includes(version.id)}
                        disabled={
                          !componentIds.includes(version.id)
                          && componentIds.length >= PUBLISH_COMPONENT_LIMIT
                        }
                        onChange={(event) => setComponentIds((all) => event.target.checked
                          ? [...all, version.id]
                          : all.filter((id) => id !== version.id))}
                      />
                      {version.label ?? `v${version.sequence_no}`}
                    </label>
                  ))}
                  {componentCandidates.length > PUBLISH_COMPONENT_LIMIT && (
                    <small className="muted">
                      {ru
                        ? `В один набор можно добавить не больше ${PUBLISH_COMPONENT_LIMIT} дополнительных версий.`
                        : `A bundle can include at most ${PUBLISH_COMPONENT_LIMIT} additional versions.`}
                    </small>
                  )}
                </fieldset>
              )}
            </section>
          )}

          {step === 1 && (
            <section className="stack" aria-labelledby="publish-description-heading">
              <strong id="publish-description-heading">{steps[1]}</strong>
              <label className="stack marketplace-publish-field">
                <span className="row marketplace-publish-label">
                  <span>{ru ? "Название" : "Title"}</span>
                  <span className="muted">{title.length} / {PUBLISH_TITLE_LIMIT}</span>
                </span>
                <input
                  className="input"
                  maxLength={PUBLISH_TITLE_LIMIT}
                  value={title}
                  onChange={(event) => { setTitle(event.target.value); setError(null); }}
                />
              </label>
              <label className="stack marketplace-publish-field">
                <span className="row marketplace-publish-label">
                  <span>{ru ? "Описание" : "Description"}</span>
                  <span className="muted">{description.length} / {PUBLISH_DESCRIPTION_LIMIT}</span>
                </span>
                <textarea
                  className="textarea"
                  maxLength={PUBLISH_DESCRIPTION_LIMIT}
                  placeholder={ru ? "Что это, для чего подходит, как печатать" : "What it is, what it fits, how to print it"}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </label>
              <label className="stack marketplace-publish-field">
                <span className="row marketplace-publish-label">
                  <span>{ru ? "Теги через запятую" : "Tags, comma separated"}</span>
                  <span className={tagList.length > PUBLISH_TAG_LIMIT ? "error" : "muted"}>
                    {tagList.length} / {PUBLISH_TAG_LIMIT}
                  </span>
                </span>
                <input
                  className="input"
                  value={tags}
                  onChange={(event) => { setTags(event.target.value); setError(null); }}
                />
              </label>
              <label className="stack marketplace-publish-field">
                <span>{ru ? "Категория" : "Category"}</span>
                <select
                  className="input"
                  value={category}
                  onChange={(event) => setCategory(event.target.value as ListingCategory)}
                >
                  {Object.entries(categories).map(([id, label]) => (
                    <option key={id} value={id}>{label}</option>
                  ))}
                </select>
              </label>
            </section>
          )}

          {step === 2 && (
            <section className="stack" aria-labelledby="publish-rights-heading">
              <strong id="publish-rights-heading">{steps[2]}</strong>
              <label className="stack marketplace-publish-field">
                <span>{ru ? "Цена, USD" : "Price, USD"}</span>
                <input
                  className="input"
                  inputMode="decimal"
                  value={priceText}
                  aria-invalid={parsedPrice === null}
                  onChange={(event) => { setPriceText(event.target.value); setError(null); }}
                />
                <small className="muted">
                  {ru
                    ? "0 = бесплатно. Платные товары станут доступны после подключения оплаты."
                    : "0 = free. Priced listings sell once payments are enabled."}
                </small>
              </label>
              <label className="stack marketplace-publish-field">
                <span>{ru ? "Лицензия" : "Licence"}</span>
                <select className="input" value={licence} onChange={(event) => setLicence(event.target.value)}>
                  {licences.map((item) => (
                    <option key={item.id} value={item.id}>{item.name}</option>
                  ))}
                </select>
              </label>
            </section>
          )}

          {step === 3 && (
            <section className="stack" aria-labelledby="publish-review-heading">
              <strong id="publish-review-heading">{steps[3]}</strong>
              <span className="muted">
                {ru ? "Так карточка будет выглядеть в каталоге." : "This is how the card will look in the catalogue."}
              </span>
              <article className="card stack marketplace-card marketplace-publish-preview" aria-label={ru ? "Предпросмотр карточки" : "Listing card preview"}>
                <strong>{title.trim()}</strong>
                <span className="muted">{categories[category]}</span>
                {description.trim() && <span className="muted marketplace-publish-preview-description">{description.trim()}</span>}
                {tagList.length > 0 && (
                  <div className="row marketplace-publish-preview-tags">
                    {tagList.map((tag, index) => <span className="chip" key={`${tag}-${index}`}>#{tag}</span>)}
                  </div>
                )}
                <div className="row marketplace-publish-preview-meta">
                  <span className="chip">
                    {parsedPrice === 0
                      ? ru ? "Бесплатно" : "Free"
                      : `${((parsedPrice ?? 0) / 100).toFixed(2)} USD`}
                  </span>
                  <span className="chip muted">{selectedLicence?.name ?? licence}</span>
                  {componentIds.length > 0 && (
                    <span className="chip">
                      {ru ? `Набор: ${componentIds.length + 1}` : `Bundle: ${componentIds.length + 1}`}
                    </span>
                  )}
                </div>
              </article>
              <span className="muted" style={{ fontSize: 12 }}>
                {ru
                  ? "Публикация создаст листинг сразу; модерация и приём оплаты в этот шаг не входят."
                  : "Publishing creates the listing immediately; moderation and payment collection are not part of this step."}
              </span>
            </section>
          )}

          {error && <div className="error" role="alert">{error}</div>}
          <div className="row marketplace-publish-actions">
            {step > 0 && (
              <button className="btn" type="button" disabled={busy} onClick={back}>
                {ru ? "Назад" : "Back"}
              </button>
            )}
            {step < STEP_IDS.length - 1 ? (
              <button className="btn primary" type="button" onClick={next}>
                {ru ? "Далее" : "Next"}
              </button>
            ) : (
              <button className="btn primary" type="submit" disabled={disabled || busy}>
                {busy ? ru ? "Публикую…" : "Publishing…" : ru ? "Опубликовать" : "Publish"}
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}
