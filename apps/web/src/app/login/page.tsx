"use client";

import { PhysicalAiClient } from "@physical-ai/contracts";
import { type FormEvent, useMemo, useState } from "react";

import { DEFAULT_BASE_URL, useSession } from "@/lib/session";

type Provider = "phone" | "email" | "yandex" | "vk";

const PROVIDERS: { id: Provider; label: string; mark: string; placeholder: string }[] = [
  { id: "phone", label: "Телефон", mark: "☎", placeholder: "+7 999 123-45-67 или любые данные" },
  { id: "email", label: "Почта", mark: "@", placeholder: "name@example.com или любые данные" },
  { id: "yandex", label: "Yandex ID", mark: "Я", placeholder: "Имя для демо-профиля" },
  { id: "vk", label: "VK ID", mark: "VK", placeholder: "Имя для демо-профиля" },
];

export default function LoginPage() {
  const { signIn } = useSession();
  const client = useMemo(() => new PhysicalAiClient({ baseUrl: DEFAULT_BASE_URL }), []);
  const [provider, setProvider] = useState<Provider>("phone");
  const [identifier, setIdentifier] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selected = PROVIDERS.find((item) => item.id === provider) ?? PROVIDERS[0];

  async function enter(event: FormEvent) {
    event.preventDefault();
    if (!identifier.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await client.demoSignIn({
        provider,
        identifier: identifier.trim(),
        display_name: provider === "yandex" || provider === "vk" ? identifier.trim() : null,
        locale: "ru",
      });
      signIn({
        baseUrl: DEFAULT_BASE_URL,
        token: result.token,
        workspaceId: result.workspace_id,
        displayName: result.user.display_name,
        address: result.user.email ?? result.user.phone ?? identifier.trim(),
      });
      // A hard navigation also works inside the Tauri webview and while Next dev compiles
      // this route for the first time; the session is already safely stored at this point.
      window.location.assign("/modeling");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-shell">
      <section className="auth-story">
        <div className="auth-logo">SOVA · PHYSICAL AI</div>
        <h1>Идея превращается<br />в точную 3D-модель.</h1>
        <p>
          Создавайте по описанию и изображению, меняйте отдельные области через AI,
          проверяйте печать и экспортируйте результат в нужный формат.
        </p>
        <div className="auth-orbit" aria-hidden="true">
          <div className="auth-object" />
          <span className="orbit orbit-one" />
          <span className="orbit orbit-two" />
        </div>
      </section>

      <section className="auth-panel">
        <form className="auth-card" onSubmit={enter}>
          <div>
            <span className="eyebrow">ДОБРО ПОЖАЛОВАТЬ</span>
            <h2>Войти в SOVA</h2>
            <p className="muted">Сейчас работает демо-вход: код и реальные операторы не нужны.</p>
          </div>

          <div className="auth-providers" role="tablist" aria-label="Способ входа">
            {PROVIDERS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={provider === item.id}
                className={`auth-provider ${provider === item.id ? "active" : ""} ${item.id}`}
                onClick={() => {
                  setProvider(item.id);
                  setError(null);
                }}
              >
                <span>{item.mark}</span>
                {item.label}
              </button>
            ))}
          </div>

          <label className="auth-field">
            <span>{selected.label}</span>
            <input
              value={identifier}
              onChange={(event) => setIdentifier(event.target.value)}
              placeholder={selected.placeholder}
              autoFocus
              autoComplete={provider === "phone" ? "tel" : provider === "email" ? "email" : "name"}
            />
          </label>

          {error && <div className="error">{error}</div>}
          <button className="auth-submit" type="submit" disabled={busy || !identifier.trim()}>
            {busy ? "Создаём пространство…" : `Продолжить через ${selected.label}`}
            <span>→</span>
          </button>
          <p className="auth-note">
            После подключения операторов здесь появятся SMS-коды и настоящие Yandex ID / VK ID.
          </p>
        </form>
      </section>
    </div>
  );
}
