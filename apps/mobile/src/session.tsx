/**
 * Client session for mobile: API base URL + bearer token + workspace in the
 * platform secure store (with an AsyncStorage fallback for web).
 * Same shape as the web session so the shared client behaves identically (T-088).
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { PhysicalAiClient } from "@physical-ai/contracts";
import Constants from "expo-constants";
import * as SecureStore from "expo-secure-store";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Platform } from "react-native";

import {
  readStoredSession,
  removeStoredSession,
  writeStoredSession,
  type SessionStore,
} from "@/src/session-storage";

export interface Session {
  baseUrl: string;
  token: string;
  workspaceId: string;
  /** Who signed in (F-083); absent for a pasted token. */
  displayName?: string | null;
  address?: string | null;
}

const asyncStorage: SessionStore = AsyncStorage;
const secureStorage: SessionStore = {
  getItem: (key) => SecureStore.getItemAsync(key),
  setItem: (key, value) =>
    SecureStore.setItemAsync(key, value, {
      keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
    }),
  removeItem: (key) => SecureStore.deleteItemAsync(key),
};

function sessionStores(): { primary: SessionStore; legacy?: SessionStore } {
  return Platform.OS === "web"
    ? { primary: asyncStorage, legacy: asyncStorage }
    : { primary: secureStorage, legacy: asyncStorage };
}

function isLoopback(url: string): boolean {
  return /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(?::|\/|$)/i.test(url);
}

function apiUrlFromExpoHost(): string | undefined {
  const hostUri = Constants.expoConfig?.hostUri;
  if (!hostUri) return undefined;

  try {
    const parsed = new URL(hostUri.includes("://") ? hostUri : `http://${hostUri}`);
    const host = parsed.hostname;
    if (!host || host === "localhost" || host === "127.0.0.1" || host === "::1") return undefined;
    return `http://${host.includes(":") ? `[${host}]` : host}:18000`;
  } catch {
    return undefined;
  }
}

/**
 * A phone cannot reach the laptop's "localhost": set EXPO_PUBLIC_API_URL (or `extra.apiUrl`)
 * to the LAN address of the API before starting Expo Go.
 */
const envBaseUrl = process.env.EXPO_PUBLIC_API_URL;
const configuredBaseUrl = Constants.expoConfig?.extra?.apiUrl as string | undefined;

export const DEFAULT_BASE_URL: string =
  envBaseUrl ??
  (configuredBaseUrl && !isLoopback(configuredBaseUrl) ? configuredBaseUrl : undefined) ??
  apiUrlFromExpoHost() ??
  configuredBaseUrl ??
  "http://localhost:18000";

interface SessionValue {
  session: Session | null;
  ready: boolean;
  client: PhysicalAiClient | null;
  signIn: (session: Session) => Promise<void>;
  selectWorkspace: (workspaceId: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const stores = sessionStores();
        setSession(await readStoredSession(stores.primary, stores.legacy));
      } catch {
        // Unreadable or unavailable secure storage: start signed out.
      } finally {
        setReady(true);
      }
    })();
  }, []);

  const value = useMemo<SessionValue>(
    () => ({
      session,
      ready,
      client: session
        ? new PhysicalAiClient({ baseUrl: session.baseUrl, token: session.token })
        : null,
      signIn: async (next) => {
        const stores = sessionStores();
        await writeStoredSession(stores.primary, next, stores.legacy);
        setSession(next);
      },
      selectWorkspace: async (workspaceId) => {
        if (!session) throw new Error("No authenticated session");
        const next = { ...session, workspaceId };
        const stores = sessionStores();
        await writeStoredSession(stores.primary, next, stores.legacy);
        setSession(next);
      },
      signOut: async () => {
        // the server forgets the token too; the local copy goes regardless
        if (session) {
          const authed = new PhysicalAiClient({ baseUrl: session.baseUrl, token: session.token });
          await authed.logout().catch(() => undefined);
        }
        const stores = sessionStores();
        try {
          await removeStoredSession(stores.primary, stores.legacy);
        } finally {
          setSession(null);
        }
      },
    }),
    [session, ready],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}
