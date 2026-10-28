"use client";

/**
 * Settings (F-083 / F-028): who you are on this server, the language answers come in, the
 * ways you can sign in, and where the printers are set up.
 */
import type { DeveloperToken, Me, PricingCatalogue } from "@physical-ai/contracts";
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
    experienceMode: "Interface mode",
    beginner: "Beginner",
    professional: "Professional",
    experienceNote:
      "Beginner keeps the main actions and guided help visible. Professional shows the complete CAD, mesh and inspection toolset by default. This changes layout, not subscription access; you can still switch inside a project.",
    saving: "Saving…",
    save: "Save",
    saved: "Saved",
    plan: "Plan",
    planNote:
      "The server checks your plan for every paid operation. Payments will be connected separately; once a subscription is active and the account has Pro, the features open in every client.",
    creditPricing: "Credits and subscriptions",
    creditPricingNote:
      "Transparent proposed prices. Purchases and debits stay disabled until production billing is connected.",
    perMonth: "/ month",
    includedCredits: "credits included",
    extraCredits: "Additional credit packs",
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
    developerApi: "Developer API",
    developerApiNote: "Keys use the same documented OpenAPI endpoints as this app. A secret is shown once and stored on the server only as a hash.",
    tokenName: "Key name",
    expires: "Expires",
    createKey: "Create key",
    secretOnce: "Copy this secret now — it cannot be shown again.",
    revoke: "Revoke",
    noKeys: "No developer keys yet.",
    deleteAccount: "Delete account",
    deleteNote: "Sign-in methods and sessions are disabled immediately. Public listings are withdrawn, and associated data is permanently erased within 30 days.",
    deleteConfirm: "Type DELETE to confirm",
    deleting: "Deleting…",
  },
  ru: {
    settings: "Настройки",
    signIn: "Войти",
    profile: "Профиль",
    name: "Имя (показывается в шапке и на маркетплейсе)",
    language: "Язык ответов ИИ и подписей",
    experienceMode: "Режим интерфейса",
    beginner: "Для начинающих",
    professional: "Для профи",
    experienceNote:
      "Для начинающих оставляет главные действия и пошаговую помощь. Для профи показывает полный набор CAD, mesh и проверочных инструментов. Это меняет интерфейс, а не подписку; в проекте режим можно временно переключить.",
    saving: "Сохраняем…",
    save: "Сохранить",
    saved: "Сохранено",
    plan: "Тариф",
    planNote:
      "Сервер проверяет тариф при каждой платной операции. Подключение оплаты будет отдельным этапом; когда подписка активна и аккаунт имеет тариф Pro, возможности открываются во всех клиентах.",
    creditPricing: "Кредиты и подписки",
    creditPricingNote:
      "Прозрачные проектные цены. Покупка и списание отключены до подключения production-биллинга.",
    perMonth: "/ месяц",
    includedCredits: "кредитов включено",
    extraCredits: "Дополнительные пакеты",
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
    developerApi: "API для разработчиков",
    developerApiNote: "Ключи работают с теми же документированными OpenAPI-методами, что и приложение. Секрет показывается один раз, на сервере хранится только хеш.",
    tokenName: "Название ключа",
    expires: "Срок",
    createKey: "Создать ключ",
    secretOnce: "Скопируйте секрет сейчас — повторно показать его нельзя.",
    revoke: "Отозвать",
    noKeys: "Ключей разработчика пока нет.",
    deleteAccount: "Удалить аккаунт",
    deleteNote: "Способы входа и сессии отключатся сразу. Публичные объявления будут сняты, а связанные данные окончательно удалены в течение 30 дней.",
    deleteConfirm: "Введите DELETE для подтверждения",
    deleting: "Удаляем…",
  },
} as const;

export default function SettingsPage() {
  const router = useRouter();
  const { session, ready, client, signIn, signOut } = useSession();
  const [me, setMe] = useState<Me | null>(null);
  const [name, setName] = useState("");
  const [locale, setLocale] = useState<Language>("ru");
  const [experienceMode, setExperienceMode] = useState<"beginner" | "professional">("beginner");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [developerTokens, setDeveloperTokens] = useState<DeveloperToken[]>([]);
  const [pricing, setPricing] = useState<PricingCatalogue | null>(null);
  const [developerLabel, setDeveloperLabel] = useState("");
  const [developerDays, setDeveloperDays] = useState(90);
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!client) return;
    let cancelled = false;
    Promise.all([
      client.me(),
      client.listDeveloperTokens(),
      client.pricing().catch(() => null),
    ])
      .then(([result, tokens, priceCatalogue]) => {
        if (cancelled) return;
        setMe(result);
        setDeveloperTokens(tokens);
        if (priceCatalogue) setPricing(priceCatalogue);
        setName(result.user.display_name ?? "");
        setLocale(result.user.locale === "en" ? "en" : "ru");
        setExperienceMode(result.user.experience_mode);
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
      const user = await client.updateMe({
        display_name: name,
        locale,
        experience_mode: experienceMode,
      });
      setMe((current) => current ? { ...current, user } : current);
      signIn({ ...session, displayName: user.display_name });
      setSaved(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function createDeveloperKey(event: FormEvent) {
    event.preventDefault();
    if (!client || !developerLabel.trim()) return;
    setBusy(true);
    setError(null);
    setCreatedSecret(null);
    try {
      const created = await client.createDeveloperToken({
        label: developerLabel.trim(),
        expires_in_days: developerDays,
      });
      setCreatedSecret(created.token);
      setDeveloperTokens((current) => [created.item, ...current]);
      setDeveloperLabel("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function revokeDeveloperKey(tokenId: string) {
    if (!client) return;
    setBusy(true);
    setError(null);
    try {
      await client.revokeDeveloperToken(tokenId);
      setDeveloperTokens((current) => current.map((token) => token.id === tokenId
        ? { ...token, revoked_at: new Date().toISOString() }
        : token));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function deleteAccount(event: FormEvent) {
    event.preventDefault();
    if (!client || deleteConfirmation !== "DELETE") return;
    setDeleting(true);
    setError(null);
    try {
      await client.deleteAccount();
      signOut();
      router.push("/delete-account?requested=1");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setDeleting(false);
    }
  }

  const t = T[locale];
  const marketPricing = pricing?.markets.find((market) => (
    locale === "ru" ? market.market === "ru" : market.market === "international"
  )) ?? null;
  const money = (minor: number, currency: string) => new Intl.NumberFormat(
    locale === "ru" ? "ru-RU" : "en-US",
    { style: "currency", currency, maximumFractionDigits: 2 },
  ).format(minor / 100);

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
          <span className="muted">{t.experienceMode}</span>
          <select
            className="input"
            value={experienceMode}
            onChange={(event) => setExperienceMode(event.target.value as "beginner" | "professional")}
            style={{ maxWidth: 240 }}
          >
            <option value="beginner">{t.beginner}</option>
            <option value="professional">{t.professional}</option>
          </select>
          <span className="muted">{t.experienceNote}</span>
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

      {marketPricing && (
        <div className="card stack">
          <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
            <strong>{t.creditPricing}</strong>
            <span className="chip">{pricing?.version} · {marketPricing.currency}</span>
          </div>
          <span className="muted">{t.creditPricingNote}</span>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
            {marketPricing.subscriptions.map((offer) => (
              <div className="stack" key={offer.code} style={{ padding: 12, border: "1px solid var(--border)", borderRadius: 12 }}>
                <strong>{locale === "ru" ? offer.title_ru : offer.title_en}</strong>
                <span>{money(offer.monthly_price_minor, marketPricing.currency)} {t.perMonth}</span>
                <span className="muted">{offer.included_credits.toLocaleString(locale)} {t.includedCredits}</span>
                {offer.seats > 1 && <span className="chip">{offer.seats} {locale === "ru" ? "мест" : "seats"}</span>}
              </div>
            ))}
          </div>
          <strong>{t.extraCredits}</strong>
          <div className="row" style={{ flexWrap: "wrap" }}>
            {marketPricing.credit_packs.map((pack) => (
              <span className="chip" key={pack.code}>
                {pack.credits.toLocaleString(locale)} · {money(pack.price_minor, marketPricing.currency)}
              </span>
            ))}
          </div>
        </div>
      )}

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

      <form className="card stack" onSubmit={createDeveloperKey}>
        <strong>{t.developerApi}</strong>
        <span className="muted">{t.developerApiNote}</span>
        <div className="row" style={{ flexWrap: "wrap", alignItems: "end" }}>
          <label className="stack" style={{ flex: 1, minWidth: 220 }}>
            <span className="muted">{t.tokenName}</span>
            <input
              className="input"
              value={developerLabel}
              maxLength={80}
              required
              onChange={(event) => setDeveloperLabel(event.target.value)}
            />
          </label>
          <label className="stack" style={{ minWidth: 150 }}>
            <span className="muted">{t.expires}</span>
            <select
              className="input"
              value={developerDays}
              onChange={(event) => setDeveloperDays(Number(event.target.value))}
            >
              <option value={30}>30 {locale === "ru" ? "дней" : "days"}</option>
              <option value={90}>90 {locale === "ru" ? "дней" : "days"}</option>
              <option value={365}>365 {locale === "ru" ? "дней" : "days"}</option>
            </select>
          </label>
          <button className="btn primary" type="submit" disabled={busy || !developerLabel.trim()}>
            {t.createKey}
          </button>
        </div>
        {createdSecret && (
          <div className="stack">
            <strong>{t.secretOnce}</strong>
            <code className="input" style={{ overflowWrap: "anywhere" }}>{createdSecret}</code>
            <button
              className="btn"
              type="button"
              style={{ alignSelf: "flex-start" }}
              onClick={() => void navigator.clipboard.writeText(createdSecret)}
            >
              {locale === "ru" ? "Копировать" : "Copy"}
            </button>
          </div>
        )}
        {developerTokens.length === 0 && <span className="muted">{t.noKeys}</span>}
        <ul className="list">
          {developerTokens.map((token) => (
            <li key={token.id} className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
              <span>
                <strong>{token.label}</strong>{" "}
                <span className="muted">
                  · {new Date(token.expires_at).toLocaleDateString(locale)}
                  {token.last_used_at && ` · ${locale === "ru" ? "использован" : "used"} ${new Date(token.last_used_at).toLocaleDateString(locale)}`}
                  {token.revoked_at && ` · ${locale === "ru" ? "отозван" : "revoked"}`}
                </span>
              </span>
              {!token.revoked_at && (
                <button className="btn" type="button" disabled={busy} onClick={() => void revokeDeveloperKey(token.id)}>
                  {t.revoke}
                </button>
              )}
            </li>
          ))}
        </ul>
      </form>

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

      <form className="card stack" onSubmit={deleteAccount} style={{ borderColor: "var(--danger, #ef4444)" }}>
        <strong>{t.deleteAccount}</strong>
        <span className="muted">{t.deleteNote}</span>
        <label className="stack" style={{ maxWidth: 320 }}>
          <span className="muted">{t.deleteConfirm}</span>
          <input
            className="input"
            value={deleteConfirmation}
            autoComplete="off"
            onChange={(event) => setDeleteConfirmation(event.target.value)}
          />
        </label>
        <button
          className="btn"
          type="submit"
          disabled={deleting || deleteConfirmation !== "DELETE"}
          style={{ alignSelf: "flex-start", color: "#ef4444", borderColor: "#ef4444" }}
        >
          {deleting ? t.deleting : t.deleteAccount}
        </button>
      </form>
    </div>
  );
}
