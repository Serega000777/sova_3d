"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { useSession } from "@/lib/session";

export function TopBar() {
  const { session, ready, signOut } = useSession();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => setMenuOpen(false), [pathname]);
  return (
    <header className="topbar">
      <button className="topbar-menu-toggle" type="button" aria-label={menuOpen ? "Закрыть меню" : "Открыть меню"} aria-controls="topbar-sections" aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}>
        <span aria-hidden="true">{menuOpen ? "✕" : "☰"}</span>
      </button>
      <Link href="/" className="brand">
        Physical AI 3D
      </Link>
      <nav id="topbar-sections" className={`topbar-links ${menuOpen ? "open" : ""}`} aria-label="Разделы">
        <Link href="/modeling" className={pathname.startsWith("/modeling") || pathname.startsWith("/projects/") ? "nav-main" : "muted"} onClick={() => setMenuOpen(false)}>Моделлинг</Link>
        <Link href="/" className={pathname === "/" ? "nav-main" : "muted"} onClick={() => setMenuOpen(false)}>Проекты</Link>
        <Link href="/convert" className={pathname.startsWith("/convert") ? "nav-main" : "muted"} onClick={() => setMenuOpen(false)}>Конвертация</Link>
        <Link href="/slicer" className={pathname.startsWith("/slicer") ? "nav-main" : "muted"} onClick={() => setMenuOpen(false)}>Слайсер</Link>
        <Link href="/market" className={pathname.startsWith("/market") ? "nav-main" : "muted"} onClick={() => setMenuOpen(false)}>Маркетплейс</Link>
        <Link href="/scanner" className={pathname.startsWith("/scanner") ? "nav-main" : "muted"} onClick={() => setMenuOpen(false)}>3D-сканер</Link>
        {ready && session && <Link href="/settings" className="muted topbar-mobile-account" onClick={() => setMenuOpen(false)}>Настройки · {session.displayName || session.address || "Профиль"}</Link>}
        {ready && session && <button className="topbar-mobile-account" type="button" onClick={() => { setMenuOpen(false); signOut(); }}>Выйти</button>}
      </nav>
      <Link href="/new" className="btn primary new-project" aria-label="Создать проект">
        +
      </Link>
      <span className="spacer" />
      {ready && session ? (
        <>
          <Link href="/settings" className="muted" title="Настройки">
            {session.displayName || session.address || "Настройки"} ⚙
          </Link>
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
