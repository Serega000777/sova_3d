"use client";

import type { ModerationEntry, ModerationPreview } from "@physical-ai/contracts";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useState } from "react";

import { LoadingScreen } from "@/components/LoadingScreen";
import { useSession } from "@/lib/session";

const ModelViewer = dynamic(
  () => import("@/components/ModelViewer").then((module) => module.ModelViewer),
  { ssr: false },
);

export default function MarketplaceModerationPage() {
  const { ready, session, client } = useSession();
  const [entries, setEntries] = useState<ModerationEntry[]>([]);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState<string | null>(null);
  const [previews, setPreviews] = useState<Record<string, ModerationPreview>>({});
  const [previewErrors, setPreviewErrors] = useState<Record<string, string>>({});
  const [selectedParts, setSelectedParts] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    if (!client) return;
    setError(null);
    try {
      const nextEntries = await client.marketplaceModerationQueue();
      const active = new Set(nextEntries.map((entry) => entry.listing.id));
      setEntries(nextEntries);
      setPreviews((current) => Object.fromEntries(Object.entries(current).filter(([id]) => active.has(id))));
      setPreviewErrors((current) => Object.fromEntries(Object.entries(current).filter(([id]) => active.has(id))));
      setSelectedParts((current) => Object.fromEntries(Object.entries(current).filter(([id]) => active.has(id))));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  useEffect(() => { void refresh(); }, [client]); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadPreview(entry: ModerationEntry) {
    if (!client) return;
    const listingId = entry.listing.id;
    setPreviewBusy(listingId);
    setPreviewErrors((current) => ({ ...current, [listingId]: "" }));
    try {
      const preview = await client.marketplaceModerationPreview(listingId);
      setPreviews((current) => ({ ...current, [listingId]: preview }));
      setSelectedParts((current) => ({
        ...current,
        [listingId]: preview.parts[0]?.part_id ?? "",
      }));
    } catch (cause) {
      setPreviewErrors((current) => ({
        ...current,
        [listingId]: cause instanceof Error ? cause.message : String(cause),
      }));
    } finally {
      setPreviewBusy(null);
    }
  }

  async function decide(entry: ModerationEntry, decision: "published" | "blocked") {
    if (!client) return;
    const reason = reasons[entry.listing.id]?.trim() ?? "";
    if (reason.length < 3) {
      setError("Укажите проверяемую причину решения (минимум 3 символа).");
      return;
    }
    setBusy(entry.listing.id);
    setError(null);
    try {
      await client.moderateMarketplaceListing(entry.listing.id, { decision, reason });
      setReasons((current) => ({ ...current, [entry.listing.id]: "" }));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  }

  if (!ready) return <LoadingScreen />;
  if (!session) return <div className="card">Войдите, чтобы открыть очередь модерации.</div>;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div><span className="marketplace-kicker">SOVA 3D</span><h1>Модерация маркетплейса</h1></div>
        <Link className="btn" href="/market">Назад в каталог</Link>
      </div>
      <p className="muted">Доступ определяется только server-owned флагом платформенного модератора; роли workspace здесь не действуют.</p>
      {error && <div className="error">{error}</div>}
      {entries.map((entry) => {
        const preview = previews[entry.listing.id];
        const selectedPart = preview?.parts.find((part) => part.part_id === selectedParts[entry.listing.id]) ?? preview?.parts[0];
        return <article className="card stack" key={entry.listing.id}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>{entry.listing.title}</strong>
            <span className="mono">{entry.listing.id}</span>
          </div>
          <span className="muted">@{entry.listing.creator_handle} · {entry.listing.domain}/{entry.listing.subcategory ?? "—"} · {entry.listing.license_name}</span>
          <p>{entry.listing.description || "Описание отсутствует."}</p>
          <span className="muted">Форматы: {entry.listing.available_formats?.join(", ") || "нет"}</span>
          <pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(entry.listing.summary, null, 2)}</pre>
          <div className="stack">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>Безопасный 3D-preview</strong>
              <button
                className="btn"
                type="button"
                disabled={previewBusy !== null}
                onClick={() => void loadPreview(entry)}
              >
                {preview ? "Обновить preview" : "Загрузить preview"}
              </button>
            </div>
            <span className="muted">Загружаются только привязанные к листингу GLB/STL model/preview assets по короткоживущим приватным URL; source/export не выдаются.</span>
            {previewBusy === entry.listing.id && <span className="muted">Загрузка preview…</span>}
            {previewErrors[entry.listing.id] && <div className="error">{previewErrors[entry.listing.id]}</div>}
            {preview && preview.parts.length === 0 && <div className="muted">Для этого листинга нет безопасного renderable preview.</div>}
            {preview && preview.parts.length > 1 && (
              <div className="row" role="radiogroup" aria-label="Части preview">
                {preview.parts.map((part) => (
                  <button
                    className={`chip ${selectedPart?.part_id === part.part_id ? "selected" : ""}`}
                    key={part.part_id}
                    type="button"
                    role="radio"
                    aria-checked={selectedPart?.part_id === part.part_id}
                    onClick={() => setSelectedParts((current) => ({ ...current, [entry.listing.id]: part.part_id }))}
                  >
                    {part.label} · {part.format.toUpperCase()}
                  </button>
                ))}
              </div>
            )}
            {selectedPart && (
              <div className="moderation-preview">
                <ModelViewer
                  key={`${selectedPart.asset_id}:${selectedPart.url}`}
                  url={selectedPart.url}
                  format={selectedPart.format}
                  selected={[]}
                  onSelect={() => undefined}
                />
              </div>
            )}
          </div>
          <label className="stack">
            <span>Обязательная причина решения</span>
            <textarea className="input" maxLength={1000} value={reasons[entry.listing.id] ?? ""} onChange={(event) => setReasons((current) => ({ ...current, [entry.listing.id]: event.target.value }))} />
          </label>
          <div className="row">
            <button className="btn primary" type="button" disabled={busy !== null} onClick={() => void decide(entry, "published")}>Одобрить</button>
            <button className="btn" type="button" disabled={busy !== null} onClick={() => void decide(entry, "blocked")}>Заблокировать</button>
          </div>
        </article>;
      })}
      {!error && entries.length === 0 && <div className="card muted">Очередь пуста.</div>}
    </div>
  );
}
