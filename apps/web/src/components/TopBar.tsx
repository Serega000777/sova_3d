"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useSession } from "@/lib/session";

type Language = "en" | "ru";
type SectionId = "modeling" | "projects" | "convert" | "slicer" | "market" | "scanner" | "plans";

const sections: { id: SectionId; href: string; icon: string; matches: (path: string) => boolean }[] = [
  { id: "modeling", href: "/modeling", icon: "⬡", matches: (path) => path.startsWith("/modeling") || path.startsWith("/projects/") },
  { id: "projects", href: "/", icon: "▦", matches: (path) => path === "/" },
  { id: "convert", href: "/convert", icon: "⇄", matches: (path) => path.startsWith("/convert") },
  { id: "slicer", href: "/slicer", icon: "▤", matches: (path) => path.startsWith("/slicer") },
  { id: "market", href: "/market", icon: "◇", matches: (path) => path.startsWith("/market") },
  { id: "scanner", href: "/scanner", icon: "⌗", matches: (path) => path.startsWith("/scanner") },
  { id: "plans", href: "/plan", icon: "▱", matches: (path) => path.startsWith("/plan") },
];

const T = {
  en: {
    sections: {
      modeling: "Modeling",
      projects: "Projects",
      convert: "Convert",
      slicer: "Slicer",
      market: "Marketplace",
      scanner: "3D scanner",
      plans: "Plans",
    },
    profile: "Profile",
    brandLabel: "Physical AI 3D — projects",
    sectionLabel: "Sections",
    settings: "Settings",
    signOut: "Sign out",
    createProject: "Create project",
    newProject: "New project",
    profileLabel: "Profile",
    signIn: "Sign in",
    closeMenu: "Close menu",
    openMenu: "Open menu",
  },
  ru: {
    sections: {
      modeling: "Моделлинг",
      projects: "Проекты",
      convert: "Конвертация",
      slicer: "Слайсер",
      market: "Маркетплейс",
      scanner: "3D-сканер",
      plans: "Планы",
    },
    profile: "Профиль",
    brandLabel: "Physical AI 3D — проекты",
    sectionLabel: "Разделы",
    settings: "Настройки",
    signOut: "Выйти",
    createProject: "Создать проект",
    newProject: "Новый проект",
    profileLabel: "Профиль",
    signIn: "Войти",
    closeMenu: "Закрыть меню",
    openMenu: "Открыть меню",
  },
} as const;

export function TopBar({ language }: { language?: Language } = {}) {
  const { session, ready, signOut } = useSession();
  const [browserLanguage, setBrowserLanguage] = useState<Language>("ru");
  useEffect(() => {
    setBrowserLanguage(navigator.language.toLowerCase().startsWith("ru") ? "ru" : "en");
  }, []);
  const resolvedLanguage = language ?? browserLanguage;
  const t = T[resolvedLanguage];
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
  const displayName = session?.displayName || session?.address || t.profile;

  return (
    <header className="topbar">
      <Link href="/" className="brand" aria-label={t.brandLabel}>
        <span className="brand-mark" aria-hidden="true">◈</span>
        <span>Physical AI <b>3D</b></span>
      </Link>

      <nav id="topbar-sections" className={`topbar-links ${menuOpen ? "open" : ""}`} aria-label={t.sectionLabel}>
        {sections.map((section) => (
          <Link
            key={section.href}
            href={section.href}
            className={section.matches(pathname) ? "nav-main" : ""}
            aria-current={section.matches(pathname) ? "page" : undefined}
            onClick={() => setMenuOpen(false)}
          >
            <span className="topbar-nav-icon" aria-hidden="true">{section.icon}</span>
            {t.sections[section.id]}
          </Link>
        ))}
        {ready && session && (
          <div className="topbar-mobile-account">
            <Link href="/settings" onClick={() => setMenuOpen(false)}>{t.settings}</Link>
            <button type="button" onClick={() => { setMenuOpen(false); signOut(); }}>{t.signOut}</button>
          </div>
        )}
      </nav>

      <div className="topbar-actions">
        <Link href="/new" className="topbar-create" aria-label={t.createProject}>
          <span className="topbar-create-icon" aria-hidden="true">＋</span>
          <span className="topbar-create-label">{t.newProject}</span>
        </Link>
        {ready && session ? (
          <details className="topbar-account" ref={accountRef}>
            <summary aria-label={`${t.profileLabel}: ${displayName}`}>
              <span className="topbar-avatar" aria-hidden="true">{displayName.slice(0, 1).toUpperCase()}</span>
              <span className="topbar-account-name">{displayName}</span>
              <span className="topbar-chevron" aria-hidden="true">⌄</span>
            </summary>
            <div className="topbar-account-menu">
              <span className="topbar-account-caption">{displayName}</span>
              <Link href="/settings">{t.settings}</Link>
              <button type="button" onClick={signOut}>{t.signOut}</button>
            </div>
          </details>
        ) : ready ? (
          <Link href="/login" className="topbar-signin">{t.signIn}</Link>
        ) : null}
        <button
          className="topbar-menu-toggle"
          type="button"
          aria-label={menuOpen ? t.closeMenu : t.openMenu}
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
