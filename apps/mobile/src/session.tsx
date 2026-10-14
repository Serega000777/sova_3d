/**
 * Client session for mobile: API base URL + bearer token + workspace in AsyncStorage.
 * Same shape as the web session so the shared client behaves identically (T-088).
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { PhysicalAiClient } from "@physical-ai/contracts";
import Constants from "expo-constants";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export interface Session {
  baseUrl: string;
  token: string;
  workspaceId: string;
  /** Who signed in (F-083); absent for a pasted token. */
  displayName?: string | null;
  address?: string | null;
}

const KEY = "physical-ai.session";

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
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const raw = await AsyncStorage.getItem(KEY);
        const parsed = raw ? (JSON.parse(raw) as Partial<Session>) : null;
        if (parsed?.baseUrl && parsed.token && parsed.workspaceId) setSession(parsed as Session);
      } catch {
        // unreadable storage: start signed out
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
        await AsyncStorage.setItem(KEY, JSON.stringify(next));
        setSession(next);
      },
      signOut: async () => {
        // the server forgets the token too; the local copy goes regardless
        if (session) {
          const authed = new PhysicalAiClient({ baseUrl: session.baseUrl, token: session.token });
          await authed.logout().catch(() => undefined);
        }
        await AsyncStorage.removeItem(KEY);
        setSession(null);
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
