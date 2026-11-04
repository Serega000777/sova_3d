"use client";

import {
  type Listing,
  type MarketplaceFile,
  type Order,
  verifiedMarketplaceDownloadUrl,
} from "@physical-ai/contracts";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { LoadingScreen } from "@/components/LoadingScreen";
import { useSession } from "@/lib/session";

function saveBlob(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

function fileLabel(file: MarketplaceFile): string {
  const labels = file.labels.length > 0 ? file.labels.join(" · ") : file.role;
  return `${labels} · ${file.format.toUpperCase()} · ${(file.byte_size / 1_048_576).toFixed(2)} MB`;
}

export default function CollectionsPage() {
  const { session, ready, client } = useSession();
  const language: "ru" | "en" =
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru")
      ? "ru"
      : "en";
  const ru = language === "ru";
  const [favorites, setFavorites] = useState<Listing[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [filesByOrder, setFilesByOrder] = useState<Record<string, MarketplaceFile[]>>({});
  const [fileErrors, setFileErrors] = useState<Record<string, string>>({});
  const [loaded, setLoaded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadRevision = useRef(0);

  const load = useCallback(async () => {
    if (!client) return;
    const request = ++loadRevision.current;
    setRefreshing(true);
    setError(null);
    try {
      const [nextFavorites, nextOrders] = await Promise.all([
        client.favoriteListings(),
        client.myOrders(),
      ]);
      if (loadRevision.current !== request) return;
      const completed = nextOrders.filter((order) => order.status === "completed");
      const fileResults = await Promise.all(completed.map(async (order) => {
        try {
          return { orderId: order.id, files: await client.orderFiles(order.id), error: null as string | null };
        } catch (reason) {
          return {
            orderId: order.id,
            files: [] as MarketplaceFile[],
            error: reason instanceof Error ? reason.message : String(reason),
          };
        }
      }));
      if (loadRevision.current !== request) return;
      setFavorites(nextFavorites);
      setOrders(completed);
      setFilesByOrder(Object.fromEntries(fileResults.map((result) => [result.orderId, result.files])));
      setFileErrors(Object.fromEntries(fileResults.flatMap((result) => (
        result.error ? [[result.orderId, result.error]] : []
      ))));
      setLoaded(true);
    } catch (reason) {
      if (loadRevision.current === request) {
        setError(reason instanceof Error ? reason.message : String(reason));
        setLoaded(true);
      }
    } finally {
      if (loadRevision.current === request) setRefreshing(false);
    }
  }, [client]);

  useEffect(() => {
    setLoaded(false);
    setFavorites([]);
    setOrders([]);
    setFilesByOrder({});
    setFileErrors({});
    void load();
    return () => { loadRevision.current += 1; };
  }, [load]);

  async function downloadFile(file: MarketplaceFile) {
    if (!client || busy) return;
    setBusy(file.asset_id);
    setError(null);
    try {
      const download = await client.download(file.asset_id);
      const url = verifiedMarketplaceDownloadUrl(file, download);
      if (!url) throw new Error(ru
        ? "Сервер вернул ссылку не на выбранный доставленный файл."
        : "The server returned a link for a different delivered file.");
      window.open(url, "_blank", "noopener");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function downloadSovaPackage(order: Order) {
    if (!client || busy || !order.project_id) return;
    const key = `sova:${order.id}`;
    setBusy(key);
    setError(null);
    try {
      const blob = await client.downloadOrderSovaPackage(order.id);
      saveBlob(`sova-project-${order.id}.sova`, blob);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  if (!ready) return <LoadingScreen />;
  if (!session) {
    return <div className="empty-stage"><Link className="btn primary" href="/login">{ru ? "Войти" : "Sign in"}</Link></div>;
  }
  if (!loaded && refreshing) return <LoadingScreen />;

  return (
    <div className="stack" style={{ maxWidth: 900 }}>
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: 0 }}>{ru ? "Избранное и покупки" : "Favorites and purchases"}</h1>
          <span className="muted">{ru ? "Только server-owned товары, завершённые цифровые покупки и доставленные файлы." : "Only server-owned favorites, completed digital purchases, and delivered files."}</span>
        </div>
        <button className="btn" type="button" disabled={refreshing} onClick={() => void load()}>{ru ? "Обновить" : "Refresh"}</button>
      </div>

      {error && <div className="error">{error}</div>}

      <section className="stack">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>{ru ? "Избранное" : "Favorites"} · {favorites.length}</h2>
          <Link href="/market">{ru ? "Открыть маркет →" : "Open market →"}</Link>
        </div>
        {favorites.length === 0 && <div className="card muted">{ru ? "Сохранённых товаров пока нет." : "No saved listings yet."}</div>}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 }}>
          {favorites.map((listing) => (
            <Link className="card stack" key={listing.id} href={`/market/${listing.id}`}>
              <strong>{listing.title}</strong>
              <span className="muted">@{listing.creator_handle} · {listing.license_name}</span>
              <span>{listing.price_cents === 0 ? (ru ? "Бесплатно" : "Free") : `${listing.currency} ${(listing.price_cents / 100).toFixed(2)}`}</span>
            </Link>
          ))}
        </div>
      </section>

      <section className="stack">
        <h2 style={{ margin: 0 }}>{ru ? "Покупки и файлы" : "Purchases and files"} · {orders.length}</h2>
        {orders.length === 0 && <div className="card muted">{ru ? "Завершённых покупок пока нет." : "No completed purchases yet."}</div>}
        {orders.map((order) => {
          const files = filesByOrder[order.id] ?? [];
          const fileError = fileErrors[order.id];
          return (
            <article className="card stack" key={order.id}>
              <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
                <span><strong>{ru ? "Заказ" : "Order"} {order.id.slice(0, 8)}</strong> · <Link href={`/market/${order.item_id}`}>{ru ? "товар" : "listing"}</Link></span>
                <span className="chip">{order.status}</span>
              </div>
              <span className="muted">{new Date(order.created_at).toLocaleString(language === "ru" ? "ru-RU" : "en-US")} · {order.currency} {(order.price_cents / 100).toFixed(2)}</span>
              {order.project_id && (
                <div className="row" style={{ flexWrap: "wrap" }}>
                  <Link className="btn" href={`/projects/${order.project_id}`}>{ru ? "Открыть полученный проект" : "Open delivered project"}</Link>
                  <button className="btn" type="button" disabled={Boolean(busy)} onClick={() => void downloadSovaPackage(order)}>
                    {busy === `sova:${order.id}` ? (ru ? "Готовим .sova…" : "Preparing .sova…") : (ru ? "Скачать редактируемый .sova" : "Download editable .sova")}
                  </button>
                </div>
              )}
              {fileError ? (
                <div className="error">{ru ? "Файлы заказа временно недоступны: " : "Order files are temporarily unavailable: "}{fileError}</div>
              ) : files.length === 0 ? (
                <span className="muted">{ru ? "В заказе нет отдельных доставленных файлов." : "This order has no separate delivered files."}</span>
              ) : (
                <div className="row" style={{ flexWrap: "wrap" }}>
                  {files.map((file) => (
                    <button className="btn" key={file.asset_id} type="button" disabled={Boolean(busy)} onClick={() => void downloadFile(file)}>
                      {busy === file.asset_id ? (ru ? "Открываем…" : "Opening…") : fileLabel(file)}
                    </button>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </section>

      <div className="card stack" style={{ borderColor: "var(--warning, #f59e0b)" }}>
        <strong>{ru ? "Граница" : "Boundary"}</strong>
        <span className="muted">{ru ? "Это библиотека цифровых покупок. Она не является очередью физического производства или историей локальных файлов устройства." : "This is a digital-purchase library. It is not a physical manufacturing queue or local-device download history."}</span>
      </div>
    </div>
  );
}
