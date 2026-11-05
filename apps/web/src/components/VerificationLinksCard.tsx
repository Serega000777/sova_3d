"use client";

import type { Schemas } from "@physical-ai/contracts";

export function VerificationLinksCard({
  links,
  createdLink,
  expiresHours,
  busy,
  language,
  onExpiresHoursChange,
  onCreate,
  onRevoke,
}: {
  links: Schemas["VerificationLinkOut"][];
  createdLink: { id: string; url: string } | null;
  expiresHours: number;
  busy: boolean;
  language: "ru" | "en";
  onExpiresHoursChange: (hours: number) => void;
  onCreate: () => void;
  onRevoke: (linkId: string) => void;
}) {
  const ru = language === "ru";
  return (
    <section id="model-verification-links" className="stack" data-testid="passport-verification-links">
      <strong>{ru ? "Ссылка для проверки отчёта" : "Report verification link"}</strong>
      <span className="muted" style={{ fontSize: 12 }}>
        {ru
          ? "Публичная ссылка на уже сохранённый отчёт этой версии — те же факты, что в PDF, без аккаунта и без цифровой подписи. Её можно отозвать в любой момент."
          : "A public link to this version's persisted report — the same facts as the PDF, with no account and no cryptographic signature. It can be revoked at any time."}
      </span>
      <div className="row">
        <select className="input" value={expiresHours} onChange={(event) => onExpiresHoursChange(Number(event.target.value))} disabled={busy}>
          <option value={24}>{ru ? "1 день" : "1 day"}</option>
          <option value={24 * 7}>{ru ? "7 дней" : "7 days"}</option>
          <option value={24 * 30}>{ru ? "30 дней" : "30 days"}</option>
        </select>
        <button className="btn" type="button" onClick={onCreate} disabled={busy}>
          {busy ? (ru ? "Создаём…" : "Creating…") : (ru ? "Создать ссылку" : "Create link")}
        </button>
      </div>
      {createdLink && (
        <div className="stack" style={{ padding: 10, borderRadius: 8, background: "var(--panel-2)" }}>
          <span className="muted" style={{ fontSize: 12 }}>{ru ? "Скопируйте сейчас — повторно показать её нельзя:" : "Copy it now — it cannot be shown again:"}</span>
          <code style={{ wordBreak: "break-all" }}>{createdLink.url}</code>
        </div>
      )}
      {links.map((link) => {
        const expired = new Date(link.expires_at).getTime() <= Date.now();
        const status = link.revoked_at
          ? (ru ? "отозвана" : "revoked")
          : expired
            ? (ru ? "истекла" : "expired")
            : (ru ? "активна" : "active");
        return (
          <div key={link.id} className="row">
            <span className="muted" style={{ fontSize: 12 }}>
              {new Date(link.created_at).toLocaleDateString(ru ? "ru-RU" : "en-US")} · {ru ? "до" : "until"} {new Date(link.expires_at).toLocaleDateString(ru ? "ru-RU" : "en-US")} · {status}
            </span>
            <span className="spacer" />
            {!link.revoked_at && <button className="btn" type="button" onClick={() => onRevoke(link.id)} disabled={busy}>{ru ? "Отозвать" : "Revoke"}</button>}
          </div>
        );
      })}
    </section>
  );
}
