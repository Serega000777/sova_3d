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
      <span className="muted">web</span>
      <Link href="/convert" className="muted">
        Convert
      </Link>
      <span className="spacer" />
      {ready && session ? (
        <>
          <span className="muted mono">{session.baseUrl}</span>
          <button className="btn" onClick={signOut}>
            Sign out
          </button>
        </>
      ) : ready ? (
        <Link href="/login" className="btn">
          Sign in
        </Link>
      ) : null}
    </header>
  );
}
