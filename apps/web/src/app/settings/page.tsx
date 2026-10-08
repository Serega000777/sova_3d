"use client";

/**
 * Settings (F-083 / F-028): who you are on this server, the language answers come in, the
 * ways you can sign in, and where the printers are set up.
 */
import type { Me } from "@physical-ai/contracts";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { LoadingScreen } from "@/components/LoadingScreen";
import { useSession } from "@/lib/session";
import { TIER_FEATURES } from "@/lib/proGate";

type Language = "en" | "ru";

const T = {
  en: {
    settings: "Settings",
    signIn: "Sign in",
    profile: "Profile",
    name: "Name (shown in the header and marketplace)",
    language: "Language for AI answers and labels",
    saving: "Saving…",
    save: "Save",
    saved: "Saved",
    plan: "Plan",
    planNote:
      "The server checks your plan for every paid operation. Payments will be connected separately; once a subscription is active and the account has Pro, the features open in every client.",
    signInMethods: "Sign-in methods",
    signInMethodsNote:
      "Phone, email, Yandex ID and VK ID are currently in demo mode; providers are connected on the server.",
    workspaces: "Workspaces",
    current: "current",
    printers: "Printers and materials",
    printersNote: "Printer profiles, hole calibration and materials for print checks.",
    openPrinters: "Open printers",
    session: "Session",
    signOut: "Sign out on this device",
  },
  ru: {
    settings: "Настройки",
    signIn: "Войти",
    profile: "Профиль",
    name: "Имя (показывается в шапке и на маркетплейсе)",
    language: "Язык ответов ИИ и подписей",
    saving: "Сохраняем…",
    save: "Сохранить",
    saved: "Сохранено",
    plan: "Тариф",
    planNote:
      "Сервер проверяет тариф при каждой платной операции. Подключение оплаты будет отдельным этапом; когда подписка активна и аккаунт имеет тариф Pro, возможности открываются во всех клиентах.",
    signInMethods: "Способы входа",
    signInMethodsNote:
      "Телефон, почта, Яндекс ID и VK ID: сейчас демо-режим, операторы подключаются на сервере.",
    workspaces: "Рабочие пространства",
    current: "текущее",
    printers: "Принтеры и материалы",
    printersNote: "Профили принтеров, калибровка отверстий, материалы для проверки печати.",
    openPrinters: "Открыть принтеры",
    session: "Сеанс",
    signOut: "Выйти на этом устройстве",
  },
} as const;

export default function SettingsPage() {
  const router = useRouter();
  const { session, ready, client, signIn, signOut } = useSession();
  const [me, setMe] = useState<Me | null>(null);
  const [name, setName] = useState("");
  const [locale, setLocale] = useState<Language>("ru");
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
        setLocale(result.user.locale === "en" ? "en" : "ru");
        if (session && session.plan !== result.user.plan) {
          signIn({ ...session, plan: result.user.plan });
        }
      })
      .catch((reason: unknown) => !cancelled && setError(reason instanceof Error ? reason.message : String(reason)));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const t = T[locale];

  if (!ready) return <LoadingScreen />;
  if (!session) {
    return (
      <div className="empty-stage">
        <h1>{t.settings}</h1>
        <Link className="btn primary" href="/login">
          {t.signIn}
        </Link>
      </div>
    );
  }

  return (
    <div className="stack" style={{ maxWidth: 720 }}>
      <h2 style={{ margin: 0 }}>{t.settings}</h2>

      <form className="card stack" onSubmit={save}>
        <strong>{t.profile}</strong>
        <label className="stack">
          <span className="muted">{t.name}</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
        </label>
        <label className="stack">
          <span className="muted">{t.language}</span>
          <select className="input" value={locale} onChange={(e) => setLocale(e.target.value as Language)} style={{ maxWidth: 240 }}>
            <option value="ru">Русский</option>
            <option value="en">English</option>
          </select>
        </label>
        {error && <div className="error">{error}</div>}
        <div className="row">
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? t.saving : t.save}
          </button>
          {saved && <span className="muted">{t.saved}</span>}
        </div>
      </form>

      <div className="card stack">
        <div className="row">
          <strong>{t.plan}</strong>
          <span className="chip">{(me?.user.plan ?? session.plan ?? "free").toUpperCase()}</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16 }}>
          <div className="stack">
            <strong>Free</strong>
            <ul className="list">
              {TIER_FEATURES.free[locale].map((feature) => <li key={feature}>{feature}</li>)}
            </ul>
          </div>
          <div className="stack">
            <strong>Pro</strong>
            <ul className="list">
              {TIER_FEATURES.pro[locale].map((feature) => <li key={feature}>{feature}</li>)}
            </ul>
          </div>
        </div>
        <span className="muted">
          {t.planNote}
        </span>
      </div>

      <div className="card stack">
        <strong>{t.signInMethods}</strong>
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
          {t.signInMethodsNote}
        </span>
      </div>

      <div className="card stack">
        <strong>{t.workspaces}</strong>
        <ul className="list">
          {me?.workspaces.map((workspace) => (
            <li key={workspace.id}>
              <strong>{workspace.name}</strong> <span className="muted">· {workspace.role}</span>
              {workspace.id === session.workspaceId && <span className="chip"> {t.current}</span>}
            </li>
          ))}
        </ul>
      </div>

      <div className="card stack">
        <strong>{t.printers}</strong>
        <span className="muted">{t.printersNote}</span>
        <Link className="btn" href="/printers" style={{ alignSelf: "flex-start" }}>
          {t.openPrinters}
        </Link>
      </div>

      <div className="card stack">
        <strong>{t.session}</strong>
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
          {t.signOut}
        </button>
      </div>
    </div>
  );
}
