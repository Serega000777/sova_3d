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
}

const KEY = "physical-ai.session";

/**
 * A phone cannot reach the laptop's "localhost": set EXPO_PUBLIC_API_URL (or `extra.apiUrl`)
 * to the LAN address of the API before starting Expo Go.
 */
export const DEFAULT_BASE_URL: string =
  process.env.EXPO_PUBLIC_API_URL ??
  (Constants.expoConfig?.extra?.apiUrl as string | undefined) ??
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
