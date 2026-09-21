"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useSession } from "@/lib/session";

const sections = [
  { href: "/modeling", label: "Моделлинг", icon: "⬡", matches: (path: string) => path.startsWith("/modeling") || path.startsWith("/projects/") },
  { href: "/", label: "Проекты", icon: "▦", matches: (path: string) => path === "/" },
  { href: "/convert", label: "Конвертация", icon: "⇄", matches: (path: string) => path.startsWith("/convert") },
  { href: "/slicer", label: "Слайсер", icon: "▤", matches: (path: string) => path.startsWith("/slicer") },
  { href: "/market", label: "Маркетплейс", icon: "◇", matches: (path: string) => path.startsWith("/market") },
  { href: "/scanner", label: "3D-сканер", icon: "⌗", matches: (path: string) => path.startsWith("/scanner") },
];

export function TopBar() {
  const { session, ready, signOut } = useSession();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const accountRef = useRef<HTMLDetailsElement>(null);
  useEffect(() => setMenuOpen(false), [pathname]);
  useEffect(() => {
    const compact = window.matchMedia("(max-width: 1180px)");
    const closeMenus = () => {
      setMenuOpen(false);
      if (accountRef.current) accountRef.current.open = false;
    };
    compact.addEventListener("change", closeMenus);
    return () => compact.removeEventListener("change", closeMenus);
  }, []);
  const displayName = session?.displayName || session?.address || "Профиль";

  return (
    <header className="topbar">
      <Link href="/" className="brand" aria-label="Physical AI 3D — проекты">
        <span className="brand-mark" aria-hidden="true">◈</span>
        <span>Physical AI <b>3D</b></span>
      </Link>

      <nav id="topbar-sections" className={`topbar-links ${menuOpen ? "open" : ""}`} aria-label="Разделы">
        {sections.map((section) => (
          <Link
            key={section.href}
            href={section.href}
            className={section.matches(pathname) ? "nav-main" : ""}
            aria-current={section.matches(pathname) ? "page" : undefined}
            onClick={() => setMenuOpen(false)}
          >
            <span className="topbar-nav-icon" aria-hidden="true">{section.icon}</span>
            {section.label}
          </Link>
        ))}
        {ready && session && (
          <div className="topbar-mobile-account">
            <Link href="/settings" onClick={() => setMenuOpen(false)}>Настройки</Link>
            <button type="button" onClick={() => { setMenuOpen(false); signOut(); }}>Выйти</button>
          </div>
        )}
      </nav>

      <div className="topbar-actions">
        <Link href="/new" className="topbar-create" aria-label="Создать проект">
          <span className="topbar-create-icon" aria-hidden="true">＋</span>
          <span className="topbar-create-label">Новый проект</span>
        </Link>
        {ready && session ? (
          <details className="topbar-account" ref={accountRef}>
            <summary aria-label={`Профиль: ${displayName}`}>
              <span className="topbar-avatar" aria-hidden="true">{displayName.slice(0, 1).toUpperCase()}</span>
              <span className="topbar-account-name">{displayName}</span>
              <span className="topbar-chevron" aria-hidden="true">⌄</span>
            </summary>
            <div className="topbar-account-menu">
              <span className="topbar-account-caption">{displayName}</span>
              <Link href="/settings">Настройки</Link>
              <button type="button" onClick={signOut}>Выйти</button>
            </div>
          </details>
        ) : ready ? (
          <Link href="/login" className="topbar-signin">Войти</Link>
        ) : null}
        <button
          className="topbar-menu-toggle"
          type="button"
          aria-label={menuOpen ? "Закрыть меню" : "Открыть меню"}
          aria-controls="topbar-sections"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span aria-hidden="true">{menuOpen ? "✕" : "☰"}</span>
        </button>
      </div>
    </header>
  );
}
