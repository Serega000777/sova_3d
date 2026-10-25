"use client";

import type { CreatorProfile, FacadeCompatibility, FitTestBody, FitTestReport, Job, Listing, MarketplaceFile, Project, SitePlanCompatibility } from "@physical-ai/contracts";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { FitTestCard } from "@/components/FitTestCard";
import { CATEGORY_LABELS, CATEGORY_LABELS_RU, price, PrintBadge, ROOM_KIND_LABELS } from "@/components/ListingCard";
import { MarketplaceFacadeFitPreview } from "@/components/MarketplaceFacadeFitPreview";
import { LoadingScreen } from "@/components/LoadingScreen";
import { MarketplaceFacadeSchedule } from "@/components/MarketplaceFacadeSchedule";
import { MarketplaceFloorPlans } from "@/components/MarketplaceFloorPlans";
import { MarketplaceSitePlan } from "@/components/MarketplaceSitePlan";
import { useSession } from "@/lib/session";

const ModelViewer = dynamic(
  () => import("@/components/ModelViewer").then((module) => module.ModelViewer),
  { ssr: false },
);

type Language = "en" | "ru";

function saveBlob(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function ListingPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { session, ready, client } = useSession();
  const [language, setLanguage] = useState<Language>("ru");
  const [listing, setListing] = useState<Listing | null>(null);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [acquiredProjectId, setAcquiredProjectId] = useState<string | null>(null);
  const [deliveredFiles, setDeliveredFiles] = useState<MarketplaceFile[]>([]);
  const [targetProjectId, setTargetProjectId] = useState<string>("");
  const [facadeCompatibility, setFacadeCompatibility] = useState<FacadeCompatibility | null>(null);
  const [facadeCompatibilityLoading, setFacadeCompatibilityLoading] = useState(false);
  const [sitePlanCompatibility, setSitePlanCompatibility] = useState<SitePlanCompatibility | null>(null);
  const [sitePlanCompatibilityLoading, setSitePlanCompatibilityLoading] = useState(false);
  const [creator, setCreator] = useState<CreatorProfile | null>(null);
  const [favorite, setFavorite] = useState(false);
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
      client.favoriteListings(),
    ]).then(async ([item, orders, projectRows, favorites]) => {
      if (cancelled) return;
      setListing(item);
      setCreator(null);
      setFavorite(favorites.some((favoriteListing) => favoriteListing.id === item.id));
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
      setDeliveredFiles(order ? await client.orderFiles(order.id) : []);
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

  useEffect(() => {
    if (!client || !listing || !targetProjectId || acquiredProjectId
      || listing.domain !== "element"
      || !["facade", "doors-windows"].includes(listing.subcategory ?? "")) {
      setFacadeCompatibility(null);
      setFacadeCompatibilityLoading(false);
      return;
    }
    let cancelled = false;
    setFacadeCompatibilityLoading(true);
    void client.facadeCompatibility(listing.id, targetProjectId).then((result) => {
      if (!cancelled) setFacadeCompatibility(result);
    }).catch(() => {
      if (!cancelled) setFacadeCompatibility(null);
    }).finally(() => {
      if (!cancelled) setFacadeCompatibilityLoading(false);
    });
    return () => { cancelled = true; };
  }, [acquiredProjectId, client, listing, targetProjectId]);

  useEffect(() => {
    if (!client || !listing?.site_plan || !targetProjectId || acquiredProjectId) {
      setSitePlanCompatibility(null);
      setSitePlanCompatibilityLoading(false);
      return;
    }
    let cancelled = false;
    setSitePlanCompatibilityLoading(true);
    void client.sitePlanCompatibility(listing.id, targetProjectId).then((result) => {
      if (!cancelled) setSitePlanCompatibility(result);
    }).catch(() => {
      if (!cancelled) setSitePlanCompatibility(null);
    }).finally(() => {
      if (!cancelled) setSitePlanCompatibilityLoading(false);
    });
    return () => { cancelled = true; };
  }, [acquiredProjectId, client, listing, targetProjectId]);

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

  async function toggleFavorite() {
    if (!client || !listing) return;
    setBusy(true);
    setError(null);
    try {
      if (favorite) await client.removeFavorite(listing.id);
      else await client.addFavorite(listing.id);
      setFavorite(!favorite);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function downloadDeliveredFile(file: MarketplaceFile) {
    if (!client) return;
    setError(null);
    try {
      const download = await client.download(file.asset_id);
      window.open(download.url, "_blank", "noopener");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function downloadHouseDocument() {
    if (!client || !listing) return;
    setBusy(true);
    setError(null);
    try {
      const document = await client.downloadHouseDocument(listing.id);
      saveBlob(`sova-house-${listing.id}.pdf`, document);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function downloadHouseSpreadsheet() {
    if (!client || !listing) return;
    setBusy(true);
    setError(null);
    try {
      const document = await client.downloadHouseSpreadsheet(listing.id);
      saveBlob(`sova-house-${listing.id}.xlsx`, document);
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
  const bundleMembers = [
    {
      id: `anchor-${listing.version_id}`,
      label: listing.title,
      size: listing.summary?.size_mm as number[] | undefined,
      thumbnailUrl: thumbnailUrls.iso ?? thumbnailUrls[thumbnailAngle] ?? null,
      anchor: true,
    },
    ...components.map((component) => ({
      id: component.id,
      label: component.label,
      size: component.summary?.size_mm as number[] | undefined,
      thumbnailUrl: componentThumbnailUrls[component.id] ?? null,
      anchor: false,
    })),
  ];
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
              {listing.house && <>
                <span className="chip">{listing.house.gross_floor_area_m2.toFixed(1)} m²</span>
                <span className="chip">{listing.house.floors} {ru ? "эт." : "floors"}</span>
                <span className="chip">
                  {{ rectangle: ru ? "Прямоугольный" : "Rectangle", l_shape: ru ? "Г-образный" : "L-shaped", t_shape: ru ? "Т-образный" : "T-shaped" }[listing.house.shape]}
                </span>
                <span className="chip mono">{(listing.house.length_mm / 1000).toFixed(1)} × {(listing.house.width_mm / 1000).toFixed(1)} m</span>
                {listing.house.rooms.length > 0 && (
                  <span className="chip">{listing.house.rooms.length} {ru ? "комн." : "rooms"}</span>
                )}
              </>}
            </div>
            {listing.description && <p style={{ margin: 0 }}>{listing.description}</p>}
            {listing.house?.rooms.length ? (
              <div className="stack" style={{ gap: 8 }}>
                <strong>{ru ? "Помещения по плану" : "Rooms in the plan"}</strong>
                <span className="muted">
                  {ru
                    ? "Типы и площади подтверждены неизменяемой операцией автопланировки."
                    : "Types and areas are backed by the immutable auto-layout operation."}
                </span>
                <div className="row" style={{ alignItems: "stretch" }}>
                  {listing.house.rooms.map((room, index) => (
                    <div className="card" key={`${room.floor_index}-${room.kind}-${index}`} style={{ minWidth: 170, padding: 12 }}>
                      <strong>{room.name}</strong>
                      <div className="muted">
                        {ROOM_KIND_LABELS[room.kind]?.[language] ?? room.kind}
                        {` · ${ru ? "этаж" : "floor"} ${room.floor_index + 1}`}
                      </div>
                      <div className="mono">{room.area_m2.toFixed(1)} m²</div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            {listing.floor_plans.length > 0 && (
              <>
                <MarketplaceFloorPlans levels={listing.floor_plans} language={language} />
                <div className="row">
                  <button className="btn" type="button" disabled={busy} onClick={() => void downloadHouseDocument()}>
                    {ru ? "Скачать паспорт дома PDF" : "Download house document PDF"}
                  </button>
                  <button className="btn" type="button" disabled={busy} onClick={() => void downloadHouseSpreadsheet()}>
                    {ru ? "Скачать ведомость XLSX" : "Download XLSX schedule"}
                  </button>
                </div>
              </>
            )}
            {listing.facade && (
              <MarketplaceFacadeSchedule facade={listing.facade} language={language} />
            )}
            {listing.site_plan && (
              <>
                <MarketplaceSitePlan site={listing.site_plan} language={language} />
                {!acquiredProject && (
                  <div className="card stack">
                    <strong>{ru ? "Совместимость с вашим участком" : "Compatibility with your plot"}</strong>
                    <label className="stack" style={{ gap: 4 }}>
                      <span>{ru ? "Проект участка" : "Plot project"}</span>
                      <select className="input" value={targetProjectId} onChange={(event) => setTargetProjectId(event.target.value)}>
                        {projects.filter((project) => project.head_version_id).map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
                      </select>
                    </label>
                    {sitePlanCompatibilityLoading && <span className="muted">{ru ? "Проверяю доказанные размеры…" : "Checking proven dimensions…"}</span>}
                    {sitePlanCompatibility?.status === "unsupported" && <span className="muted">{ru
                      ? "В выбранном проекте нужен участок, сохранённый успешной сборкой композиции."
                      : "The selected project needs a plot saved by a successful site composition."}</span>}
                    {sitePlanCompatibility && sitePlanCompatibility.status !== "unsupported" && (
                      <div className="stack" style={{ gap: 8 }}>
                        <span className={`chip ${sitePlanCompatibility.status === "compatible" ? "status-green" : sitePlanCompatibility.status === "rotated" ? "status-yellow" : "status-red"}`}>
                          {sitePlanCompatibility.status === "compatible"
                            ? (ru ? "Композиция помещается" : "Composition fits")
                            : sitePlanCompatibility.status === "rotated"
                              ? (ru ? "Помещается после поворота на 90°" : "Fits after a 90° rotation")
                              : (ru ? "Композиция не помещается" : "Composition does not fit")}
                        </span>
                        {sitePlanCompatibility.required_size_mm && sitePlanCompatibility.available_size_mm && (
                          <span className="mono muted">
                            {(sitePlanCompatibility.required_size_mm[0] / 1000).toFixed(1)} × {(sitePlanCompatibility.required_size_mm[1] / 1000).toFixed(1)} m
                            {" → "}
                            {(sitePlanCompatibility.available_size_mm[0] / 1000).toFixed(1)} × {(sitePlanCompatibility.available_size_mm[1] / 1000).toFixed(1)} m
                          </span>
                        )}
                        {sitePlanCompatibility.terrain_corner_delta_mm && (
                          <div className="stack" style={{ gap: 6 }}>
                            <span className="mono">
                              {ru ? "Профиль рельефа после поворота" : "Terrain profile after rotation"}
                              {" "}{sitePlanCompatibility.terrain_rotation_deg}° · {ru ? "макс. разница" : "max delta"}
                              {" "}{sitePlanCompatibility.terrain_max_delta_mm?.toFixed(0)} mm
                            </span>
                            <div className="row" style={{ flexWrap: "wrap" }}>
                              {sitePlanCompatibility.terrain_corner_delta_mm.map((delta, index) => (
                                <span className="chip mono" key={["SW", "SE", "NE", "NW"][index]}>
                                  {["SW", "SE", "NE", "NW"][index]} {delta >= 0 ? "+" : ""}{delta.toFixed(0)} mm
                                </span>
                              ))}
                            </div>
                            <span className="muted">{ru
                              ? "Разницы измерены относительно юго-западного угла для точно совпадающего контура. Это не допуск на земляные работы."
                              : "Deltas are measured from the south-west corner for an exactly matching envelope. They are not an earthworks tolerance."}</span>
                          </div>
                        )}
                        {!sitePlanCompatibility.terrain_corner_delta_mm && sitePlanCompatibility.status !== "incompatible" && (
                          <span className="muted">{ru
                            ? "Профиль углов нельзя сравнить без точного совпадения контура: на большем участке ещё не выбрана позиция композиции."
                            : "Corner profiles cannot be compared without an exact envelope match: the composition has no selected position on a larger plot."}</span>
                        )}
                        <span className="muted">{ru
                          ? "Сравниваются обе оси участка, а при точном контуре — измеренный профиль четырёх углов. Нормативные отступы и коллизии требуют отдельной проверки."
                          : "Both plot axes are compared and, for an exact envelope, the measured four-corner profile. Statutory setbacks and collisions need a separate check."}</span>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
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
              <div className="stack" style={{ gap: 8 }}>
                <Link className="btn primary" href={`/projects/${acquiredProject.id}`}>
                  {ru ? "Открыть полученный проект" : "Open acquired project"}
                </Link>
                {deliveredFiles.length > 0 && (
                  <div className="stack" style={{ gap: 6 }}>
                    <strong>{ru ? "Файлы покупки" : "Purchased files"}</strong>
                    <span className="muted">
                      {ru
                        ? "Это конкретные файлы, сохранённые в вашей копии при получении товара."
                        : "These are the concrete files saved in your copy when the item was acquired."}
                    </span>
                    <div className="row">
                      {deliveredFiles.map((file) => (
                        <button
                          className="btn"
                          type="button"
                          key={`${file.role}-${file.asset_id}`}
                          onClick={() => void downloadDeliveredFile(file)}
                        >
                          {ru ? "Скачать" : "Download"} {file.labels.join(" / ")} · {file.format.toUpperCase()} · {(file.byte_size / 1_000_000).toFixed(2)} MB
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="row">
                <button className="btn primary" type="button" disabled={busy} onClick={() => void take()}>
                  {busy ? (ru ? "Получаю…" : "Taking…") : listing.price_cents === 0 ? (ru ? "Получить бесплатно" : "Get it free") : (ru ? `Купить за ${price(listing, language)}` : `Buy for ${price(listing, language)}`)}
                </button>
                <button className="btn" type="button" disabled={busy} onClick={() => void addToCart()}>
                  {ru ? "В корзину" : "Add to cart"}
                </button>
                <button className="btn" type="button" disabled={busy} aria-pressed={favorite} onClick={() => void toggleFavorite()}>
                  {favorite ? (ru ? "★ В избранном" : "★ Favorited") : (ru ? "☆ В избранное" : "☆ Favorite")}
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
          <span className="muted">{ru
            ? "Номера едины для обзора и списка файлов. Показаны только заранее сохранённые превью."
            : "Numbers are shared by the overview and file list. Only previously saved previews are shown."}</span>
          <div className="marketplace-bundle-board" aria-label={ru ? "Нумерованный обзор модулей" : "Numbered module overview"}>
            {bundleMembers.map((member, index) => (
              <article className="marketplace-bundle-tile" key={member.id}>
                <span className="marketplace-module-number" aria-label={`${ru ? "Модуль" : "Module"} ${index + 1}`}>{index + 1}</span>
                {member.thumbnailUrl ? (
                  <img src={member.thumbnailUrl} alt={`${index + 1}. ${member.label}`} />
                ) : (
                  <span className="marketplace-bundle-missing">{ru ? "Нет сохранённого превью" : "No saved preview"}</span>
                )}
                <strong>{member.label}</strong>
                {member.size && <span className="mono muted">{member.size.map((value) => value.toFixed(0)).join(" × ")} mm</span>}
              </article>
            ))}
          </div>
          <ol className="list marketplace-bundle-list">
            {bundleMembers.map((member, index) => {
              const component = index > 0 ? components[index - 1] : null;
              return (
                <li key={member.id} className="row marketplace-bundle-component">
                  <span className="marketplace-module-number" aria-hidden="true">{index + 1}</span>
                  <span className="marketplace-bundle-component-label">{member.label}{member.anchor ? ` · ${ru ? "основная модель" : "anchor model"}` : ""}</span>
                  <span className="row">
                    {member.size && <span className="chip mono">{member.size.map((value) => value.toFixed(0)).join(" × ")} mm</span>}
                    {component?.print_verified?.status === "green" && <span className="chip status-green">{ru ? "✓ Проверено" : "✓ Verified"}</span>}
                    {component?.print_verified?.status === "yellow" && <span className="chip status-yellow">{ru ? "Требует настройки" : "Setup needed"}</span>}
                    {component?.print_verified?.status === "red" && <span className="chip status-red">{ru ? "Проверка не пройдена" : "Check failed"}</span>}
                  </span>
                </li>
              );
            })}
          </ol>
        </section>
      )}

      <section className="stack">
        <h2 style={{ marginBottom: 0 }}>{ru ? "Примерить в проекте" : "Fit in a project"}</h2>
        {!acquiredProject ? (
          <div className="card stack">
            {listing.domain === "element" && ["facade", "doors-windows"].includes(listing.subcategory ?? "") && (
              <div className="stack">
                <strong>{ru ? "Совместимость с фасадом" : "Facade compatibility"}</strong>
                <label className="stack" style={{ gap: 4 }}>
                  <span>{ru ? "Проект дома" : "House project"}</span>
                  <select className="input" value={targetProjectId} onChange={(event) => setTargetProjectId(event.target.value)}>
                    {projects.filter((project) => project.head_version_id).map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
                  </select>
                </label>
                {facadeCompatibilityLoading && <span className="muted">{ru ? "Проверяю сохранённые проёмы…" : "Checking saved openings…"}</span>}
                {facadeCompatibility?.status === "unsupported" && <span className="muted">{ru
                  ? "Выбранный проект должен иметь сохранённый exact-фасад с адресными проёмами."
                  : "The selected project needs a saved exact facade with addressed openings."}</span>}
                {facadeCompatibility && facadeCompatibility.status !== "unsupported" && (
                  <div className="stack">
                    <span className={`chip ${facadeCompatibility.status === "complete" ? "status-green" : facadeCompatibility.status === "partial" ? "status-yellow" : "status-red"}`}>
                      {ru
                        ? `${facadeCompatibility.matched_openings} из ${facadeCompatibility.total_openings} проёмов совпадают по габаритам`
                        : `${facadeCompatibility.matched_openings} of ${facadeCompatibility.total_openings} openings match by envelope`}
                    </span>
                    <ul className="list">
                      {facadeCompatibility.openings.map((opening) => (
                        <li key={opening.opening_id} className="row">
                          <span>{opening.side} · {ru ? "этаж" : "floor"} {opening.floor ?? "—"} · {opening.width_mm.toFixed(0)} × {opening.height_mm.toFixed(0)} mm</span>
                          <span className={opening.matches.length ? "status-green" : "muted"}>{opening.matches.length
                            ? opening.matches.map((match) => match.label).join(", ")
                            : (ru ? "нет модуля" : "no module")}</span>
                        </li>
                      ))}
                    </ul>
                    <MarketplaceFacadeFitPreview compatibility={facadeCompatibility} language={language} />
                    <span className="muted">{ru
                      ? "Проверены сохранённые габариты модулей, толщина стены и адреса проёмов. Точная mesh-проверка доступна после покупки."
                      : "This checks saved module envelopes, wall thickness and opening addresses. An exact mesh fit test is available after acquisition."}</span>
                  </div>
                )}
              </div>
            )}
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
