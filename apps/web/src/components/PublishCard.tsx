"use client";

/** Publish one explicit kept version through a bounded four-step marketplace flow. */
import type {
  Licence,
  Listing,
  ListingBody,
  ListingCategory,
  ListingDomain,
  MarketplaceFacets,
  Project,
  Version,
} from "@physical-ai/contracts";
import Link from "next/link";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { CATEGORY_LABELS, CATEGORY_LABELS_RU, price } from "@/components/ListingCard";
import {
  buildListingBody,
  eligibleAnchorVersions,
  eligibleComponentVersions,
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
  marketplaceFacets: MarketplaceFacets;
  disabled: boolean;
  onPublish: (body: ListingBody) => Promise<void>;
  onWithdraw: (listingId: string, back: boolean) => Promise<void>;
}

const STEP_IDS = ["files", "description", "rights", "review"] as const;
const DOMAIN_LABELS: Record<ListingDomain, { en: string; ru: string }> = {
  figure: { en: "Figures", ru: "Фигуры" },
  element: { en: "Elements", ru: "Элементы" },
  house: { en: "Houses", ru: "Дома" },
  yard: { en: "Yards", ru: "Дворы" },
  printable: { en: "For printing", ru: "Для печати" },
  other: { en: "Other", ru: "Другое" },
};

export function PublishCard({
  project,
  versions,
  licences,
  listings,
  marketplaceFacets,
  disabled,
  onPublish,
  onWithdraw,
}: PublishCardProps) {
  const [step, setStep] = useState(0);
  const [title, setTitle] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [category, setCategory] = useState<ListingCategory>("print");
  const [domain, setDomain] = useState<ListingDomain>("printable");
  const [subcategory, setSubcategory] = useState("");
  const [tags, setTags] = useState("");
  const [priceText, setPriceText] = useState("0");
  const [licence, setLicence] = useState(project.license_id ?? "CC-BY-4.0");
  const [busy, setBusy] = useState(false);
  const [componentIds, setComponentIds] = useState<string[]>([]);
  const [anchorVersionId, setAnchorVersionId] = useState(project.head_version_id ?? "");
  const [error, setError] = useState<string | null>(null);
  const [ru, setRu] = useState(true);
  const stepHeadingRef = useRef<HTMLHeadingElement>(null);
  const anchorCandidates = eligibleAnchorVersions(
    versions,
    listings.map((item) => item.version_id),
  );
  const anchorVersion = anchorCandidates.find((version) => version.id === anchorVersionId)
    ?? anchorCandidates.find((version) => version.id === project.head_version_id)
    ?? anchorCandidates[0];
  const effectiveAnchorVersionId = anchorVersion?.id ?? "";
  const componentCandidates = eligibleComponentVersions(versions, effectiveAnchorVersionId);
  const tagList = listingTags(tags);
  const parsedPrice = parsePriceCents(priceText);
  const categories = ru ? CATEGORY_LABELS_RU : CATEGORY_LABELS;
  const selectedLicence = licences.find((item) => item.id === licence);
  const subcategories = marketplaceFacets.domains.find((item) => item.id === domain)
    ?.subcategories ?? [];
  const steps = ru
    ? ["Файлы", "Описание", "Цена и права", "Проверка"]
    : ["Files", "Description", "Price & rights", "Review"];

  useEffect(() => {
    setRu(navigator.language.toLowerCase().startsWith("ru"));
  }, []);

  useEffect(() => {
    setStep(0);
    setTitle(project.name);
    setDescription(project.description ?? "");
    setCategory("print");
    setDomain("printable");
    setSubcategory("");
    setTags("");
    setPriceText("0");
    setLicence(project.license_id ?? "CC-BY-4.0");
    setAnchorVersionId(project.head_version_id ?? "");
    setComponentIds([]);
    setError(null);
  }, [project.id]);

  useEffect(() => {
    stepHeadingRef.current?.focus();
  }, [step]);

  function resetWizard() {
    setStep(0);
    setTitle(project.name);
    setDescription(project.description ?? "");
    setCategory("print");
    setDomain("printable");
    setSubcategory("");
    setTags("");
    setPriceText("0");
    setLicence(project.license_id ?? "CC-BY-4.0");
    setAnchorVersionId(project.head_version_id ?? "");
    setComponentIds([]);
    setError(null);
  }

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
      anchorVersionId: effectiveAnchorVersionId,
      title,
      description,
      category,
      domain,
      subcategory,
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
      resetWizard();
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
      {!anchorVersion ? (
        <span className="muted">
          {ru
            ? "Нет неопубликованной завершённой версии с сохранёнными файлами."
            : "There is no unpublished finalized version with saved files."}
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
          <span className="sr-only" aria-live="polite">
            {ru ? `Шаг ${step + 1} из ${steps.length}: ${steps[step]}` : `Step ${step + 1} of ${steps.length}: ${steps[step]}`}
          </span>

          {step === 0 && (
            <section className="stack" aria-labelledby="publish-files-heading">
              <h3 ref={stepHeadingRef} tabIndex={-1} id="publish-files-heading" className="marketplace-publish-heading">{steps[0]}</h3>
              <span className="muted">
                {ru
                  ? "Выберите точную завершённую версию проекта. Публикуются уже сохранённые в ней файлы; новые форматы здесь не загружаются."
                  : "Choose the exact finalized project version. This publishes its saved files; it does not upload new formats."}
              </span>
              <label className="stack marketplace-publish-field">
                <span>{ru ? "Основная версия" : "Primary version"}</span>
                <select
                  className="input"
                  value={effectiveAnchorVersionId}
                  onChange={(event) => {
                    const nextId = event.target.value;
                    setAnchorVersionId(nextId);
                    setComponentIds((all) => all.filter((id) => id !== nextId));
                  }}
                >
                  {anchorCandidates.map((version) => (
                    <option key={version.id} value={version.id}>
                      {version.label ?? `v${version.sequence_no}`} · {version.assets.length} {ru ? "файл(а)" : "file(s)"}
                    </option>
                  ))}
                </select>
              </label>
              <div className="marketplace-publish-file row">
                <span aria-hidden="true">◆</span>
                <span>
                  <strong>{anchorVersion?.label ?? project.name}</strong>
                  <small className="muted">
                    {ru ? "Основная версия" : "Primary version"}
                  </small>
                </span>
              </div>
              <small className="muted">
                {ru
                  ? "Для набора доступны только завершённые версии, в которых сохранён хотя бы один файл."
                  : "Only finalized versions with at least one saved file are available for a bundle."}
              </small>
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
              <h3 ref={stepHeadingRef} tabIndex={-1} id="publish-description-heading" className="marketplace-publish-heading">{steps[1]}</h3>
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
                <span>{ru ? "Раздел каталога" : "Catalogue section"}</span>
                <select
                  className="input"
                  value={domain}
                  onChange={(event) => {
                    setDomain(event.target.value as ListingDomain);
                    setSubcategory("");
                  }}
                >
                  {Object.entries(DOMAIN_LABELS).map(([id, labels]) => (
                    <option key={id} value={id}>{ru ? labels.ru : labels.en}</option>
                  ))}
                </select>
              </label>
              <label className="stack marketplace-publish-field">
                <span>{ru ? "Подкатегория" : "Subcategory"}</span>
                <select
                  className="input"
                  value={subcategory}
                  onChange={(event) => setSubcategory(event.target.value)}
                >
                  <option value="">{ru ? "Без подкатегории" : "No subcategory"}</option>
                  {subcategories.map((item) => (
                    <option key={item.id} value={item.id}>
                      {ru ? item.label_ru : item.label_en}
                    </option>
                  ))}
                </select>
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
              <h3 ref={stepHeadingRef} tabIndex={-1} id="publish-rights-heading" className="marketplace-publish-heading">{steps[2]}</h3>
              <label className="stack marketplace-publish-field">
                <span>{ru ? "Цена, USD" : "Price, USD"}</span>
                <input
                  className="input"
                  inputMode="decimal"
                  value={priceText}
                  aria-invalid={parsedPrice === null}
                  aria-describedby={parsedPrice === null
                    ? "publish-price-help publish-price-error"
                    : "publish-price-help"}
                  onChange={(event) => { setPriceText(event.target.value); setError(null); }}
                />
                <small className="muted" id="publish-price-help">
                  {ru
                    ? "0 = бесплатно; не больше двух знаков после запятой. Платные товары станут доступны после подключения оплаты."
                    : "0 = free; use at most two decimal places. Priced listings sell once payments are enabled."}
                </small>
                {parsedPrice === null && (
                  <small className="error" id="publish-price-error">
                    {ru ? "Введите неотрицательную цену максимум с двумя знаками после запятой." : "Enter a non-negative price with at most two decimal places."}
                  </small>
                )}
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
              <h3 ref={stepHeadingRef} tabIndex={-1} id="publish-review-heading" className="marketplace-publish-heading">{steps[3]}</h3>
              <span className="muted">
                {ru ? "Так карточка будет выглядеть в каталоге." : "This is how the card will look in the catalogue."}
              </span>
              <article className="card stack marketplace-card marketplace-publish-preview" aria-label={ru ? "Предпросмотр карточки" : "Listing card preview"}>
                <strong>{title.trim()}</strong>
                <span className="muted">
                  {DOMAIN_LABELS[domain][ru ? "ru" : "en"]} · {categories[category]}
                </span>
                {description.trim() && <span className="muted marketplace-publish-preview-description">{description.trim()}</span>}
                {tagList.length > 0 && (
                  <div className="row marketplace-publish-preview-tags">
                    {tagList.map((tag, index) => <span className="chip" key={`${tag}-${index}`}>#{tag}</span>)}
                  </div>
                )}
                <div className="row marketplace-publish-preview-meta">
                  <span className="chip mono">
                    {anchorVersion.label ?? `v${anchorVersion.sequence_no}`}
                  </span>
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
