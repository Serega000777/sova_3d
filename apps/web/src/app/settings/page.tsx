"use client";

/**
 * Settings (F-083 / F-028): who you are on this server, the language answers come in, the
 * ways you can sign in, and where the printers are set up.
 */
import type { Me } from "@physical-ai/contracts";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { useSession } from "@/lib/session";

export default function SettingsPage() {
  const router = useRouter();
  const { session, ready, client, signIn, signOut } = useSession();
  const [me, setMe] = useState<Me | null>(null);
  const [name, setName] = useState("");
  const [locale, setLocale] = useState("ru");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client) return;
    let cancelled = false;
    client
      .me()
      .then((result) => {
        if (cancelled) return;
        setMe(result);
        setName(result.user.display_name ?? "");
        setLocale(result.user.locale || "ru");
      })
      .catch((reason: unknown) => !cancelled && setError(reason instanceof Error ? reason.message : String(reason)));
    return () => {
      cancelled = true;
    };
  }, [client]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!client || !session) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const user = await client.updateMe({ display_name: name, locale });
      signIn({ ...session, displayName: user.display_name });
      setSaved(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  if (!ready) return null;
  if (!session) {
    return (
      <div className="empty-stage">
        <h1>Настройки</h1>
        <Link className="btn primary" href="/login">
          Войти
        </Link>
      </div>
    );
  }

  return (
    <div className="stack" style={{ maxWidth: 720 }}>
      <h2 style={{ margin: 0 }}>Настройки</h2>

      <form className="card stack" onSubmit={save}>
        <strong>Профиль</strong>
        <label className="stack">
          <span className="muted">Имя (показывается в шапке и на маркетплейсе)</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
        </label>
        <label className="stack">
          <span className="muted">Язык ответов ИИ и подписей</span>
          <select className="input" value={locale} onChange={(e) => setLocale(e.target.value)} style={{ maxWidth: 240 }}>
            <option value="ru">Русский</option>
            <option value="en">English</option>
          </select>
        </label>
        {error && <div className="error">{error}</div>}
        <div className="row">
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "Сохраняем…" : "Сохранить"}
          </button>
          {saved && <span className="muted">Сохранено</span>}
        </div>
      </form>

      <div className="card stack">
        <strong>Способы входа</strong>
        <ul className="list">
          {me?.identities.map((identity) => (
            <li key={`${identity.provider}-${identity.subject ?? identity.display_name ?? ""}`}>
              <strong>{identity.label}</strong>{" "}
              <span className="muted">{identity.subject ?? identity.display_name ?? ""}</span>
            </li>
          ))}
          {me && me.identities.length === 0 && <li className="muted">—</li>}
        </ul>
        <span className="muted">
          Телефон, почта, Яндекс ID и VK ID: сейчас демо-режим, операторы подключаются на сервере.
        </span>
      </div>

      <div className="card stack">
        <strong>Рабочие пространства</strong>
        <ul className="list">
          {me?.workspaces.map((workspace) => (
            <li key={workspace.id}>
              <strong>{workspace.name}</strong> <span className="muted">· {workspace.role}</span>
              {workspace.id === session.workspaceId && <span className="chip"> текущее</span>}
            </li>
          ))}
        </ul>
      </div>

      <div className="card stack">
        <strong>Принтеры и материалы</strong>
        <span className="muted">Профили принтеров, калибровка отверстий, материалы для проверки печати.</span>
        <Link className="btn" href="/printers" style={{ alignSelf: "flex-start" }}>
          Открыть принтеры
        </Link>
      </div>

      <div className="card stack">
        <strong>Сеанс</strong>
        <span className="muted mono">{session.baseUrl}</span>
        <button
          className="btn"
          type="button"
          style={{ alignSelf: "flex-start" }}
          onClick={() => {
            signOut();
            router.push("/login");
          }}
        >
          Выйти на этом устройстве
        </button>
      </div>
    </div>
  );
}
