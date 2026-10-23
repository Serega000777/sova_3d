"use client";

import type { CreatorProfile, FitTestBody, FitTestReport, Job, Listing, Project } from "@physical-ai/contracts";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { FitTestCard } from "@/components/FitTestCard";
import { CATEGORY_LABELS, CATEGORY_LABELS_RU, price, PrintBadge } from "@/components/ListingCard";
import { LoadingScreen } from "@/components/LoadingScreen";
import { useSession } from "@/lib/session";

const ModelViewer = dynamic(
  () => import("@/components/ModelViewer").then((module) => module.ModelViewer),
  { ssr: false },
);

type Language = "en" | "ru";

export default function ListingPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { session, ready, client } = useSession();
  const [language, setLanguage] = useState<Language>("ru");
  const [listing, setListing] = useState<Listing | null>(null);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [acquiredProjectId, setAcquiredProjectId] = useState<string | null>(null);
  const [targetProjectId, setTargetProjectId] = useState<string>("");
  const [creator, setCreator] = useState<CreatorProfile | null>(null);
  const [thumbnailUrls, setThumbnailUrls] = useState<Record<string, string>>({});
  const [componentThumbnailUrls, setComponentThumbnailUrls] = useState<Record<string, string>>({});
  const [thumbnailAngle, setThumbnailAngle] = useState("iso");
  const [displayMode, setDisplayMode] = useState<"solid" | "wire">("solid");
  const [targetSize, setTargetSize] = useState(["", "", ""]);
  const [configuration, setConfiguration] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ru = language === "ru";

  useEffect(() => {
    setLanguage(navigator.language.toLowerCase().startsWith("ru") ? "ru" : "en");
  }, []);

  useEffect(() => {
    if (!client || !session) return;
    let cancelled = false;
    void Promise.all([
      client.getListing(params.id),
      client.myOrders(),
      client.listProjects(session.workspaceId),
    ]).then(async ([item, orders, projectRows]) => {
      if (cancelled) return;
      setListing(item);
      setCreator(null);
      setThumbnailUrls({});
      setComponentThumbnailUrls({});
      const thumbnails = item.thumbnails ?? [];
      const preferredAngle = thumbnails.some((thumbnail) => thumbnail.angle === "iso")
        ? "iso"
        : (thumbnails[0]?.angle ?? "iso");
      setThumbnailAngle(preferredAngle);
      setConfiguration(Object.fromEntries((item.parameters ?? []).map((parameter) => [parameter.key, String(parameter.value)])));
      setProjects(projectRows);
      const order = orders.find(
        (candidate) => candidate.item_id === item.id && candidate.workspace_id === session.workspaceId,
      );
      const acquiredId = order?.project_id ?? null;
      setAcquiredProjectId(acquiredId);
      setTargetProjectId(
        projectRows.find((project) => project.id !== acquiredId && project.head_version_id)?.id ?? "",
      );
      void client.creatorPage(item.creator_handle).then((page) => {
        if (!cancelled) setCreator(page.profile);
      });
      void Promise.all(
        thumbnails.map(async (thumbnail) => [
          thumbnail.angle,
          (await client.download(thumbnail.asset_id)).url,
        ] as const),
      ).then((rows) => {
        if (!cancelled) setThumbnailUrls(Object.fromEntries(rows));
      }).catch(() => {
        if (!cancelled) setThumbnailUrls({});
      });
      void Promise.all(
        (item.components ?? [])
          .filter((component) => component.thumbnail_asset_id)
          .map(async (component) => [
            component.id,
            (await client.download(component.thumbnail_asset_id!)).url,
          ] as const),
      ).then((rows) => {
        if (!cancelled) setComponentThumbnailUrls(Object.fromEntries(rows));
      }).catch(() => {
        if (!cancelled) setComponentThumbnailUrls({});
      });
      if (item.model_asset_id) {
        const download = await client.download(item.model_asset_id);
        if (!cancelled) setModelUrl(download.url);
      }
    }).catch((reason: unknown) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
    });
    return () => { cancelled = true; };
  }, [client, params.id, session]);

  const acquiredProject = projects.find((project) => project.id === acquiredProjectId) ?? null;
  const targetProject = projects.find((project) => project.id === targetProjectId) ?? null;
  const size = listing?.summary?.size_mm as number[] | undefined;
  const numericTarget = targetSize.map(Number);
  const preview = useMemo(() => {
    if (!size || numericTarget.some((value) => !Number.isFinite(value) || value <= 0)) return null;
    return size.slice(0, 3).map((value, index) => numericTarget[index] - value);
  }, [numericTarget, size]);

  async function take() {
    if (!client || !session || !listing) return;
    setBusy(true);
    setError(null);
    try {
      const parameters = listing.parameters ?? [];
      const values = parameters.map((parameter) => ({
        operation: parameter.operation,
        parameter: parameter.parameter,
        value: Number(configuration[parameter.key]),
      }));
      if (values.some((value, index) => !Number.isFinite(value.value)
        || value.value < parameters[index].min
        || value.value > parameters[index].max)) {
        throw new Error(ru ? "Проверьте значения параметров." : "Check the parameter values.");
      }
      const changed = values.filter((value, index) => value.value !== parameters[index].value);
      const acquired = await client.acquireListing(listing.id, session.workspaceId, changed);
      if (acquired.configuration_job_id) {
        const job = await client.waitForJob(acquired.configuration_job_id, { timeoutMs: 8 * 60_000 });
        if (job.status !== "succeeded") {
          throw new Error((job.error as { message?: string } | null)?.message
            ?? (ru ? "Модель получена, но настройка не завершилась." : "The model was acquired, but configuration failed."));
        }
      }
      router.push(`/projects/${acquired.project_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function addToCart() {
    if (!client || !session || !listing) return;
    setBusy(true);
    setError(null);
    try {
      await client.addToCart(listing.id, session.workspaceId);
      router.push("/cart");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function runFitTest(body: Omit<FitTestBody, "version_a_id">): Promise<Job | null> {
    if (!client || !targetProject?.head_version_id) return null;
    setError(null);
    try {
      const accepted = await client.startFitTest({
        ...body,
        version_a_id: targetProject.head_version_id,
      });
      const job = await client.waitForJob(accepted.job_id);
      if (job.status !== "succeeded") {
        throw new Error((job.error as { message?: string } | null)?.message ?? (ru ? "Проверка не выполнена" : "Fit test failed"));
      }
      return job;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      return null;
    }
  }

  async function applyFitFix(fix: NonNullable<FitTestReport["advice"]["fix"]>) {
    if (!client || !targetProject?.head_version_id) return;
    const accepted = await client.createEdit(targetProject.head_version_id, {
      operations: fix.operations as { type: string; [key: string]: unknown }[],
      label: fix.label,
    });
    const job = await client.waitForJob(accepted.job_id);
    if (job.status !== "succeeded") {
      throw new Error((job.error as { message?: string } | null)?.message ?? (ru ? "Исправление не применено" : "Fix failed"));
    }
  }

  async function createFitAssembly(fitTestId: string) {
    if (!client || !targetProject) return;
    const made = await client.createFitAssembly(fitTestId);
    router.push(`/projects/${targetProject.id}?version=${made.version_id}`);
  }

  if (!ready) return <LoadingScreen />;
  if (!session) return <div className="card"><p>{ru ? "Войдите, чтобы открыть товар." : "Sign in to see the listing."}</p></div>;
  if (!listing) return <div className="muted">{error ?? (ru ? "Загрузка…" : "Loading…")}</div>;

  const categories = ru ? CATEGORY_LABELS_RU : CATEGORY_LABELS;
  const components = listing.components ?? [];
  const thumbnails = listing.thumbnails ?? [];
  const creatorWebsite = creator?.website && /^https?:\/\//i.test(creator.website)
    ? creator.website
    : null;
  return (
    <div className="stack marketplace-product">
      <div className="project-layout">
        <div className="stack">
          <div>
            <h1 style={{ margin: 0 }}>{listing.title}</h1>
            <span className="muted">
              {ru ? "автор" : "by"} <Link href={`/creators/${listing.creator_handle}`}>@{listing.creator_handle}</Link>
              {creator && ` · ${creator.followers} ${ru ? "подписчиков" : "followers"}`}
              {` · ${categories[listing.category] ?? listing.category}`}
            </span>
          </div>
          {thumbnailUrls[thumbnailAngle] && (
            <img
              className="marketplace-product-thumbnail"
              src={thumbnailUrls[thumbnailAngle]}
              alt={`${listing.title} · ${thumbnailAngle}`}
            />
          )}
          {thumbnails.length > 0 && (
            <div className="marketplace-thumbnail-gallery" role="radiogroup" aria-label={ru ? "Ракурсы товара" : "Listing views"}>
              {thumbnails.map((thumbnail) => (
                <button
                  key={thumbnail.angle}
                  type="button"
                  role="radio"
                  aria-checked={thumbnailAngle === thumbnail.angle}
                  className={thumbnailAngle === thumbnail.angle ? "active" : ""}
                  onClick={() => setThumbnailAngle(thumbnail.angle)}
                >
                  {thumbnailUrls[thumbnail.angle]
                    ? <img src={thumbnailUrls[thumbnail.angle]} alt={`${listing.title} · ${thumbnail.angle}`} />
                    : <span>{thumbnail.angle}</span>}
                </button>
              ))}
            </div>
          )}
          <div className="row marketplace-view-tabs">
            <button type="button" className={`chip ${displayMode === "solid" ? "selected" : ""}`} onClick={() => setDisplayMode("solid")}>
              {ru ? "Осмотр" : "Inspect"}
            </button>
            <button type="button" className={`chip ${displayMode === "wire" ? "selected" : ""}`} onClick={() => setDisplayMode("wire")}>
              {ru ? "Каркас" : "Wireframe"}
            </button>
          </div>
          <ModelViewer url={modelUrl} selected={[]} onSelect={() => undefined} displayMode={displayMode} />
        </div>
        <div className="stack">
          <div className="card stack marketplace-buy-card">
            <div className="row">
              <span className="chip">{price(listing, language)}</span>
              <span className="chip muted">{listing.license_name}</span>
              <span className={`chip ${listing.commercial_use ? "status-green" : "status-yellow"}`}>
                {listing.commercial_use ? (ru ? "Коммерческое" : "Commercial") : (ru ? "Личное" : "Personal")}
              </span>
              <PrintBadge listing={listing} language={language} />
              {(listing.available_formats ?? []).map((format) => (
                <span className="chip mono" key={format}>{format.toUpperCase()}</span>
              ))}
              {size && <span className="chip mono">{size.map((value) => value.toFixed(0)).join(" × ")} mm</span>}
            </div>
            {listing.description && <p style={{ margin: 0 }}>{listing.description}</p>}
            {(listing.parameters ?? []).length > 0 && !acquiredProject && (
              <div className="stack" style={{ gap: 8 }}>
                <strong>{ru ? "Настроить точную модель" : "Configure the exact model"}</strong>
                <span className="muted">
                  {ru
                    ? "Параметры взяты из неизменяемого CAD-дерева автора. После получения ядро пересоберёт вашу копию."
                    : "These controls come from the creator's immutable CAD tree. The kernel rebuilds your copy after acquisition."}
                </span>
                {(listing.parameters ?? []).map((parameter) => (
                  <label className="row" key={parameter.key} style={{ justifyContent: "space-between" }}>
                    <span className="mono">{parameter.operation} · {parameter.parameter}</span>
                    <span className="row">
                      <input
                        className="input"
                        style={{ width: 120 }}
                        type="number"
                        min={parameter.min}
                        max={parameter.max}
                        step="any"
                        value={configuration[parameter.key] ?? String(parameter.value)}
                        onChange={(event) => setConfiguration((current) => ({ ...current, [parameter.key]: event.target.value }))}
                      />
                      <span className="muted">{parameter.unit}</span>
                    </span>
                  </label>
                ))}
              </div>
            )}
            {acquiredProject ? (
              <Link className="btn primary" href={`/projects/${acquiredProject.id}`}>
                {ru ? "Открыть купленный проект" : "Open acquired project"}
              </Link>
            ) : (
              <div className="row">
                <button className="btn primary" type="button" disabled={busy} onClick={() => void take()}>
                  {busy ? (ru ? "Получаю…" : "Taking…") : listing.price_cents === 0 ? (ru ? "Получить бесплатно" : "Get it free") : (ru ? `Купить за ${price(listing, language)}` : `Buy for ${price(listing, language)}`)}
                </button>
                <button className="btn" type="button" disabled={busy} onClick={() => void addToCart()}>
                  {ru ? "В корзину" : "Add to cart"}
                </button>
              </div>
            )}
            {error && <div className="error">{error}</div>}
          </div>
          {creator && (
            <aside className="card stack marketplace-creator-summary">
              <span className="marketplace-kicker">{ru ? "Автор" : "Creator"}</span>
              <strong>{creator.display_name}</strong>
              <Link href={`/creators/${creator.handle}`}>@{creator.handle}</Link>
              {creator.bio && <span className="muted">{creator.bio}</span>}
              {creatorWebsite && (
                <a href={creatorWebsite} target="_blank" rel="noreferrer">{ru ? "Сайт автора" : "Creator website"}</a>
              )}
              <span className="muted">
                {creator.followers} {ru ? "подписчиков" : "followers"} · {creator.listings} {ru ? "публикаций" : "listings"}
              </span>
            </aside>
          )}
        </div>
      </div>

      {components.length > 0 && (
        <section className="card stack">
          <strong>{ru ? `Состав набора · ${components.length + 1}` : `Bundle contents · ${components.length + 1}`}</strong>
          <ul className="list">
            <li>{listing.title} · {ru ? "основная модель" : "anchor model"}</li>
            {components.map((component) => (
              <li key={component.id} className="row marketplace-bundle-component">
                {componentThumbnailUrls[component.id] && (
                  <img
                    className="marketplace-component-thumbnail"
                    src={componentThumbnailUrls[component.id]}
                    alt={component.label}
                  />
                )}
                <span className="marketplace-bundle-component-label">{component.label}</span>
                <span className="row">
                  {Array.isArray(component.summary?.size_mm) && <span className="chip mono">{(component.summary.size_mm as number[]).map((value) => value.toFixed(0)).join(" × ")} mm</span>}
                  {component.print_verified?.status === "green" && <span className="chip status-green">{ru ? "✓ Проверено" : "✓ Verified"}</span>}
                  {component.print_verified?.status === "yellow" && <span className="chip status-yellow">{ru ? "Требует настройки" : "Setup needed"}</span>}
                  {component.print_verified?.status === "red" && <span className="chip status-red">{ru ? "Проверка не пройдена" : "Check failed"}</span>}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="stack">
        <h2 style={{ marginBottom: 0 }}>{ru ? "Примерить в проекте" : "Fit in a project"}</h2>
        {!acquiredProject ? (
          <div className="card stack">
            <strong>{ru ? "Предварительно по заявленным размерам" : "Declared-dimension preview"}</strong>
            <span className="muted">
              {ru ? "Введите размер проёма или места X × Y × Z, мм." : "Enter the target opening or space X × Y × Z in mm."}
            </span>
            <div className="row">
              {targetSize.map((value, index) => (
                <input key={index} className="input" style={{ width: 110 }} type="number" min="0.1" step="0.1" placeholder={["X, мм", "Y, мм", "Z, мм"][index]} value={value} onChange={(event) => setTargetSize((all) => all.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} />
              ))}
            </div>
            {preview && <span className="mono">Δ {preview.map((value) => `${value >= 0 ? "+" : ""}${value.toFixed(1)}`).join(" × ")} mm</span>}
            <span className="muted">{ru ? "Точная проверка доступна после покупки." : "An exact mesh fit test is available after acquisition."}</span>
          </div>
        ) : (
          <div className="stack">
            <label className="stack" style={{ gap: 4 }}>
              <span>{ru ? "Проект для проверки" : "Project to test against"}</span>
              <select className="input" value={targetProjectId} onChange={(event) => setTargetProjectId(event.target.value)}>
                {projects.filter((project) => project.id !== acquiredProject.id && project.head_version_id).map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
              </select>
            </label>
            {targetProject ? (
              <FitTestCard projects={projects} currentProjectId={targetProject.id} defaultOtherId={acquiredProject.id} disabled={busy} onRun={runFitTest} onApplyFix={applyFitFix} onCreateAssembly={createFitAssembly} />
            ) : (
              <div className="card muted">{ru ? "Создайте второй проект для точной проверки." : "Create another project for an exact fit test."}</div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
