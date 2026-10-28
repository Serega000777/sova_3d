import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Удаление аккаунта · Sova 3D",
  description: "Как удалить аккаунт Sova 3D и связанные данные.",
};

export default function DeleteAccountPage() {
  return (
    <article className="stack" style={{ maxWidth: 760, margin: "0 auto" }}>
      <div className="card stack">
        <span className="chip" style={{ alignSelf: "flex-start" }}>Sova 3D · Account deletion</span>
        <h1 style={{ margin: 0 }}>Удаление аккаунта / Delete account</h1>
        <p className="muted">
          Удаление доступно прямо в приложении: <strong>Профиль → Удалить аккаунт</strong>.
          В веб-версии откройте <strong>Настройки → Удалить аккаунт</strong>.
        </p>
        <p className="muted">
          Deletion is available in the app under <strong>Profile → Delete account</strong>, or
          on the web under <strong>Settings → Delete account</strong>.
        </p>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <Link className="btn primary" href="/settings">Открыть настройки / Open settings</Link>
          <Link className="btn" href="/login">Войти / Sign in</Link>
        </div>
      </div>

      <section className="card stack">
        <h2 style={{ margin: 0 }}>Что произойдёт / What happens</h2>
        <ul className="list">
          <li>Все активные сессии, API-ключи и способы входа отключаются сразу.</li>
          <li>Публичные объявления снимаются, доступ к чужим командным пространствам прекращается.</li>
          <li>Персональные данные очищаются, связанные проекты и файлы удаляются не позднее чем через 30 дней.</li>
          <li>Записи, которые закон требует хранить дольше, сохраняются только на обязательный срок и без публичного профиля.</li>
        </ul>
        <p className="muted">
          Sessions, API keys and sign-in identities are disabled immediately. Public listings
          are withdrawn. Associated projects and files are erased within 30 days. Records that
          must be retained by law are kept only for the required period.
        </p>
      </section>

      <nav className="row" aria-label="Legal pages">
        <Link href="/privacy">Политика конфиденциальности</Link>
        <Link href="/terms">Условия использования</Link>
      </nav>
    </article>
  );
}
