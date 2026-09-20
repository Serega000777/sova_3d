"use client";

import Link from "next/link";

import { useSession } from "@/lib/session";

export function TopBar() {
  const { session, ready, signOut } = useSession();
  return (
    <header className="topbar">
      <Link href="/" className="brand">
        Physical AI 3D
      </Link>
      <Link href="/modeling" className="nav-main">
        Моделлинг
      </Link>
      <Link href="/" className="muted">
        Проекты
      </Link>
      <Link href="/convert" className="muted">
        Конвертация
      </Link>
      <Link href="/printers" className="muted">
        Слайсер
      </Link>
      <Link href="/market" className="muted">
        Маркетплейс
      </Link>
      <Link href="/scanner" className="muted">
        3D-сканер
      </Link>
      <Link href="/new" className="btn primary new-project" aria-label="Создать проект">
        +
      </Link>
      <span className="spacer" />
      {ready && session ? (
        <>
          <span className="muted" title={session.baseUrl}>
            {session.displayName || session.address || "signed in"}
          </span>
          <button className="btn" onClick={signOut}>
            Выйти
          </button>
        </>
      ) : ready ? (
        <Link href="/login" className="btn">
          Войти
        </Link>
      ) : null}
    </header>
  );
}
