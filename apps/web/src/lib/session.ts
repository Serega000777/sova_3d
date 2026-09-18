"use client";

/**
 * Client session: API base URL + bearer token + workspace, kept in localStorage.
 * OIDC lands later; today the token comes from `python -m app.cli create-user`.
 *
 * One module-level store backs every `useSession()` caller, so the top bar and the
 * page that signed in stay in step (and other tabs follow via the storage event).
 */
import { PhysicalAiClient } from "@physical-ai/contracts";
import { useMemo, useSyncExternalStore } from "react";

export interface Session {
  baseUrl: string;
  token: string;
  workspaceId: string;
}

const KEY = "physical-ai.session";
export const DEFAULT_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:18000";

export function loadSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Session>;
    if (parsed.baseUrl && parsed.token && parsed.workspaceId) return parsed as Session;
  } catch {
    // corrupted or unavailable storage: treat as signed out
  }
  return null;
}

export function saveSession(session: Session | null): void {
  try {
    if (session) window.localStorage.setItem(KEY, JSON.stringify(session));
    else window.localStorage.removeItem(KEY);
  } catch {
    // storage may be blocked; the in-memory copy still works for this tab
  }
}

let current: Session | null = null;
let hydrated = false;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key !== null && event.key !== KEY) return;
    current = loadSession();
    emit();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** Cached so React sees a stable reference between renders. */
function getSnapshot(): Session | null {
  if (!hydrated) {
    current = loadSession();
    hydrated = true;
  }
  return current;
}

/** The server renders signed out; the first client pass matches, then hydration fills it in. */
function getServerSnapshot(): Session | null {
  return null;
}

function setSession(next: Session | null): void {
  saveSession(next);
  current = next;
  hydrated = true;
  emit();
}

export function useSession(): {
  session: Session | null;
  ready: boolean;
  client: PhysicalAiClient | null;
  signIn: (session: Session) => void;
  signOut: () => void;
} {
  const session = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const ready = useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
  const client = useMemo(
    () =>
      session ? new PhysicalAiClient({ baseUrl: session.baseUrl, token: session.token }) : null,
    [session],
  );
  return { session, ready, client, signIn: setSession, signOut: () => setSession(null) };
}
