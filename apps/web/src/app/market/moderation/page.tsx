"use client";

import type { ModerationEntry } from "@physical-ai/contracts";
import Link from "next/link";
import { useEffect, useState } from "react";

import { LoadingScreen } from "@/components/LoadingScreen";
import { useSession } from "@/lib/session";

export default function MarketplaceModerationPage() {
  const { ready, session, client } = useSession();
  const [entries, setEntries] = useState<ModerationEntry[]>([]);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    if (!client) return;
    setError(null);
    try {
      setEntries(await client.marketplaceModerationQueue());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  useEffect(() => { void refresh(); }, [client]); // eslint-disable-line react-hooks/exhaustive-deps

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
      {entries.map((entry) => (
        <article className="card stack" key={entry.listing.id}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>{entry.listing.title}</strong>
            <span className="mono">{entry.listing.id}</span>
          </div>
          <span className="muted">@{entry.listing.creator_handle} · {entry.listing.domain}/{entry.listing.subcategory ?? "—"} · {entry.listing.license_name}</span>
          <p>{entry.listing.description || "Описание отсутствует."}</p>
          <span className="muted">Форматы: {entry.listing.available_formats?.join(", ") || "нет"}</span>
          <pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(entry.listing.summary, null, 2)}</pre>
          <label className="stack">
            <span>Обязательная причина решения</span>
            <textarea className="input" maxLength={1000} value={reasons[entry.listing.id] ?? ""} onChange={(event) => setReasons((current) => ({ ...current, [entry.listing.id]: event.target.value }))} />
          </label>
          <div className="row">
            <button className="btn primary" type="button" disabled={busy !== null} onClick={() => void decide(entry, "published")}>Одобрить</button>
            <button className="btn" type="button" disabled={busy !== null} onClick={() => void decide(entry, "blocked")}>Заблокировать</button>
          </div>
        </article>
      ))}
      {!error && entries.length === 0 && <div className="card muted">Очередь пуста.</div>}
    </div>
  );
}
