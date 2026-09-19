"use client";

/**
 * Sign in (T-164, F-083): a phone or an email and the code that reaches it, or a Yandex ID /
 * VK ID account. The server says which ways are on; in demo mode the code confirms itself
 * (any address signs in) and the account buttons lead to a demo consent page.
 */
import { ApiError, PhysicalAiClient, type SignInMethods } from "@physical-ai/contracts";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useEffect, useMemo, useRef, useState } from "react";

import { DEFAULT_BASE_URL, useSession } from "@/lib/session";

type Channel = "phone" | "email";
type Provider = "yandex" | "vk";

const T = {
  ru: {
    title: "Вход",
    lead: "Опишите предмет — получите модель, которую можно править и печатать.",
    phone: "Телефон",
    email: "Почта",
    phonePlaceholder: "+7 999 123-45-67",
    emailPlaceholder: "you@example.com",
    getCode: "Получить код",
    sending: "Отправляем…",
    codeSent: (a: string) => `Код отправлен на ${a}`,
    code: "Код из сообщения",
    enter: "Войти",
    checking: "Проверяем…",
    another: "Другой номер или почта",
    resend: "Отправить ещё раз",
    or: "или",
    demoCode: (c: string) => `Демо-режим: оператор не подключён, ваш код — ${c}`,
    demoOauth: "Демо-режим: реальный сервис не подключён. Как вас называть?",
    yourName: "Ваше имя",
    continueAs: "Продолжить",
    cancel: "Отмена",
    wrongCode: (n: number) => `Неверный код, осталось попыток: ${n}`,
    gone: "Код больше не действует — запросите новый",
    tooMany: "Слишком много кодов для этого адреса, попробуйте позже",
    off: "Этот способ входа на сервере выключен",
    welcome: "Добро пожаловать!",
  },
  en: {
    title: "Sign in",
    lead: "Describe an object, get a model you can edit and print.",
    phone: "Phone",
    email: "Email",
    phonePlaceholder: "+1 415 555 0100",
    emailPlaceholder: "you@example.com",
    getCode: "Send me a code",
    sending: "Sending…",
    codeSent: (a: string) => `A code was sent to ${a}`,
    code: "Code from the message",
    enter: "Sign in",
    checking: "Checking…",
    another: "Another number or email",
    resend: "Send again",
    or: "or",
    demoCode: (c: string) => `Demo mode: no operator is connected — your code is ${c}`,
    demoOauth: "Demo mode: the real service is not connected. What should we call you?",
    yourName: "Your name",
    continueAs: "Continue",
    cancel: "Cancel",
    wrongCode: (n: number) => `Wrong code, ${n} attempt(s) left`,
    gone: "That code no longer works — ask for a new one",
    tooMany: "Too many codes for this address, try again later",
    off: "This way of signing in is switched off on the server",
    welcome: "Welcome!",
  },
};

function describe(err: unknown, t: (typeof T)["en"]): string {
  if (err instanceof ApiError) {
    if (err.code === "code_rejected") {
      const left = (err.details as { attempts_left?: number } | undefined)?.attempts_left;
      return t.wrongCode(left ?? 0);
    }
    if (err.code === "challenge_gone") return t.gone;
    if (err.code === "too_many_codes") return t.tooMany;
    if (err.code === "signin_not_enabled") return t.off;
    return err.message;
  }
  return err instanceof Error ? err.message : String(err);
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { signIn } = useSession();
  const language: "en" | "ru" =
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru")
      ? "ru"
      : "en";
  const t = T[language];
  const baseUrl = DEFAULT_BASE_URL;
  const client = useMemo(() => new PhysicalAiClient({ baseUrl }), [baseUrl]);
  const [methods, setMethods] = useState<SignInMethods | null>(null);
  const [channel, setChannel] = useState<Channel>("phone");
  const [address, setAddress] = useState("");
  const [challenge, setChallenge] = useState<{ id: string; address: string; devCode: string | null } | null>(
    null,
  );
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const codeInput = useRef<HTMLInputElement>(null);

  // the demo consent page: the "provider" sent us back here with ?stub=1&provider=&state=
  const consentProvider = params.get("stub") === "1" ? (params.get("provider") as Provider | null) : null;
  const consentState = params.get("state");
  const [consentName, setConsentName] = useState("");

  useEffect(() => {
    let cancelled = false;
    client
      .signInMethods()
      .then((m) => {
        if (cancelled) return;
        setMethods(m);
        if (m.code.length > 0 && !m.code.includes(channel)) setChannel(m.code[0]);
      })
      .catch((err: unknown) => !cancelled && setError(describe(err, t)));
    return () => {
      cancelled = true;
    };
    // the language dictionary is static per page load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  function finish(session: { token: string; workspace_id: string; user: { display_name: string | null; email: string | null; phone: string | null } }) {
    signIn({
      baseUrl,
      token: session.token,
      workspaceId: session.workspace_id,
      displayName: session.user.display_name,
      address: session.user.email ?? session.user.phone ?? null,
    });
    router.push("/");
  }

  async function requestCode(event?: FormEvent) {
    event?.preventDefault();
    if (!address.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const started = await client.requestCode({ channel, address: address.trim(), locale: language });
      if (started.dev_code) {
        // demo delivery: nothing to type in from anywhere — the code confirms itself
        finish(await client.verifyCode(started.challenge_id, started.dev_code));
        return;
      }
      setChallenge({ id: started.challenge_id, address: started.address, devCode: null });
      setCode("");
      setTimeout(() => codeInput.current?.focus(), 0);
    } catch (err) {
      setError(describe(err, t));
    } finally {
      setBusy(false);
    }
  }

  async function verify(event: FormEvent) {
    event.preventDefault();
    if (!challenge || code.replace(/\D/g, "").length < 6) return;
    setBusy(true);
    setError(null);
    try {
      finish(await client.verifyCode(challenge.id, code.replace(/\D/g, "")));
    } catch (err) {
      const message = describe(err, t);
      setError(message);
      if (err instanceof ApiError && err.code === "challenge_gone") setChallenge(null);
    } finally {
      setBusy(false);
    }
  }

  async function startOAuth(provider: Provider) {
    setBusy(true);
    setError(null);
    try {
      const redirect = `${window.location.origin}/login`;
      const started = await client.oauthStart(provider, redirect, language);
      window.location.assign(started.authorize_url);
    } catch (err) {
      setError(describe(err, t));
      setBusy(false);
    }
  }

  async function finishConsent(event: FormEvent) {
    event.preventDefault();
    if (!consentProvider || !consentState || !consentName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      finish(await client.oauthCallback(consentProvider, `stub:${consentName.trim()}`, consentState));
    } catch (err) {
      setError(describe(err, t));
      setBusy(false);
    }
  }

  const label = methods?.labels ?? { yandex: "Yandex ID", vk: "VK ID" };

  if (consentProvider && consentState) {
    return (
      <div className="signin">
        <div className="card stack signin-card">
          <div className={`oauth-badge ${consentProvider}`}>{label[consentProvider]}</div>
          <p className="muted" style={{ margin: 0 }}>
            {t.demoOauth}
          </p>
          <form className="stack" onSubmit={finishConsent}>
            <input
              className="input"
              placeholder={t.yourName}
              value={consentName}
              onChange={(e) => setConsentName(e.target.value)}
              autoFocus
              maxLength={100}
            />
            {error && <div className="error">{error}</div>}
            <div className="row">
              <button className="btn primary" type="submit" disabled={busy || !consentName.trim()}>
                {busy ? t.checking : t.continueAs}
              </button>
              <button className="btn" type="button" onClick={() => router.replace("/login")}>
                {t.cancel}
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="signin">
      <div className="card stack signin-card">
        <div>
          <h2 style={{ margin: 0 }}>{t.title}</h2>
          <p className="muted" style={{ margin: "6px 0 0" }}>
            {t.lead}
          </p>
        </div>

        {methods && methods.code.length > 0 && (
          <>
            <div className="segmented" role="tablist">
              {methods.code.map((c) => (
                <button
                  key={c}
                  type="button"
                  role="tab"
                  aria-selected={channel === c}
                  className={`chip ${channel === c ? "selected" : ""}`}
                  disabled={busy || !!challenge}
                  onClick={() => setChannel(c)}
                >
                  {c === "phone" ? t.phone : t.email}
                </button>
              ))}
            </div>

            {challenge ? (
              <form className="stack" onSubmit={verify}>
                <span className="muted">{t.codeSent(challenge.address)}</span>
                {challenge.devCode && (
                  <div className="demo-note" data-testid="dev-code">
                    {t.demoCode(challenge.devCode)}
                  </div>
                )}
                <input
                  ref={codeInput}
                  className="input code-input"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="••••••"
                  maxLength={7}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/[^\d ]/g, ""))}
                  aria-label={t.code}
                />
                {error && <div className="error">{error}</div>}
                <button
                  className="btn primary"
                  type="submit"
                  disabled={busy || code.replace(/\D/g, "").length < 6}
                >
                  {busy ? t.checking : t.enter}
                </button>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <button className="btn" type="button" disabled={busy} onClick={() => void requestCode()}>
                    {t.resend}
                  </button>
                  <button
                    className="btn"
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setChallenge(null);
                      setError(null);
                    }}
                  >
                    {t.another}
                  </button>
                </div>
              </form>
            ) : (
              <form className="stack" onSubmit={requestCode}>
                <input
                  className="input"
                  type={channel === "phone" ? "tel" : "email"}
                  inputMode={channel === "phone" ? "tel" : "email"}
                  autoComplete={channel === "phone" ? "tel" : "email"}
                  placeholder={channel === "phone" ? t.phonePlaceholder : t.emailPlaceholder}
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  autoFocus
                />
                {error && <div className="error">{error}</div>}
                <button className="btn primary" type="submit" disabled={busy || !address.trim()}>
                  {busy ? t.sending : t.getCode}
                </button>
              </form>
            )}
          </>
        )}

        {methods && methods.oauth.length > 0 && (
          <>
            {methods.code.length > 0 && <div className="divider muted">{t.or}</div>}
            <div className="stack">
              {methods.oauth.map((provider) => (
                <button
                  key={provider}
                  type="button"
                  className={`btn oauth ${provider}`}
                  disabled={busy}
                  onClick={() => void startOAuth(provider)}
                >
                  <span className="oauth-mark" aria-hidden="true">
                    {provider === "yandex" ? "Я" : "VK"}
                  </span>
                  {label[provider]}
                </button>
              ))}
            </div>
          </>
        )}

        {methods && methods.code.length === 0 && methods.oauth.length === 0 && (
          <div className="error">{t.off}</div>
        )}

      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
