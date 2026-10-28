export interface StoredSession {
  baseUrl: string;
  token: string;
  workspaceId: string;
  displayName?: string | null;
  address?: string | null;
}

export interface SessionStore {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
}

export const LEGACY_SESSION_KEY = "physical-ai.session";
export const SECURE_SESSION_KEY = "physical-ai.session.secure.v1";

function optionalString(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === "string";
}

export function parseStoredSession(raw: string): StoredSession | null {
  try {
    const value = JSON.parse(raw) as Record<string, unknown> | null;
    if (
      !value ||
      Array.isArray(value) ||
      typeof value.baseUrl !== "string" ||
      !value.baseUrl.trim() ||
      typeof value.token !== "string" ||
      !value.token ||
      typeof value.workspaceId !== "string" ||
      !value.workspaceId ||
      !optionalString(value.displayName) ||
      !optionalString(value.address)
    ) {
      return null;
    }

    return {
      baseUrl: value.baseUrl,
      token: value.token,
      workspaceId: value.workspaceId,
      ...(value.displayName !== undefined ? { displayName: value.displayName } : {}),
      ...(value.address !== undefined ? { address: value.address } : {}),
    };
  } catch {
    return null;
  }
}

export async function readStoredSession(
  secureStore: SessionStore,
  legacyStore?: SessionStore,
): Promise<StoredSession | null> {
  const secureRaw = await secureStore.getItem(SECURE_SESSION_KEY);
  if (secureRaw !== null) {
    const session = parseStoredSession(secureRaw);
    if (session) {
      if (legacyStore) await legacyStore.removeItem(LEGACY_SESSION_KEY);
      return session;
    }
    await secureStore.removeItem(SECURE_SESSION_KEY);
    if (legacyStore) await legacyStore.removeItem(LEGACY_SESSION_KEY);
    return null;
  }

  if (!legacyStore) return null;
  const legacyRaw = await legacyStore.getItem(LEGACY_SESSION_KEY);
  if (legacyRaw === null) return null;
  const session = parseStoredSession(legacyRaw);
  if (!session) {
    await legacyStore.removeItem(LEGACY_SESSION_KEY);
    return null;
  }

  await secureStore.setItem(SECURE_SESSION_KEY, JSON.stringify(session));
  await legacyStore.removeItem(LEGACY_SESSION_KEY);
  return session;
}

export async function writeStoredSession(
  store: SessionStore,
  session: StoredSession,
  legacyStore?: SessionStore,
): Promise<void> {
  await store.setItem(SECURE_SESSION_KEY, JSON.stringify(session));
  if (legacyStore) await legacyStore.removeItem(LEGACY_SESSION_KEY);
}

export async function removeStoredSession(
  store: SessionStore,
  legacyStore?: SessionStore,
): Promise<void> {
  const removals = [store.removeItem(SECURE_SESSION_KEY)];
  if (legacyStore) removals.push(legacyStore.removeItem(LEGACY_SESSION_KEY));
  const results = await Promise.allSettled(removals);
  const failed = results.find((result): result is PromiseRejectedResult => result.status === "rejected");
  if (failed) throw failed.reason;
}
