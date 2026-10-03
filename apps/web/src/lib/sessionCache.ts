/**
 * Versioned localStorage format for the cached client session. Pure (no React, no DOM) so the
 * migration can be unit tested.
 *
 * Before the tier rename the cache was an unversioned flat object whose `plan` used the old
 * names: "pro" = basic (now "free"), "profi" = paid (now "pro"). Reading those values as-is
 * would unlock paid UI for old basic sessions, so unversioned entries are always treated as
 * legacy and remapped. Entries written by this module carry `v` and are never remapped.
 */
import type { AccountTier } from "@physical-ai/contracts";

export const SESSION_CACHE_VERSION = 2;

export interface CachedSession {
  baseUrl: string;
  token: string;
  workspaceId: string;
  displayName?: string | null;
  address?: string | null;
  plan?: AccountTier;
}

const TIERS: readonly string[] = ["free", "pro"];

function legacyPlan(plan: unknown): AccountTier | undefined {
  if (plan === "pro") return "free";
  if (plan === "profi") return "pro";
  return undefined; // absent or unknown: leave unset, the UI treats it as free
}

function currentPlan(plan: unknown): AccountTier | undefined {
  return typeof plan === "string" && TIERS.includes(plan) ? (plan as AccountTier) : undefined;
}

function validated(value: unknown, plan: AccountTier | undefined): CachedSession | null {
  if (!value || typeof value !== "object") return null;
  const s = value as Record<string, unknown>;
  if (!s.baseUrl || !s.token || !s.workspaceId) return null;
  const { plan: _ignored, ...rest } = s;
  return (plan ? { ...rest, plan } : rest) as unknown as CachedSession;
}

/** Parses a stored value. `migrated` is true when it was a legacy entry that should be rewritten. */
export function parseCachedSession(raw: string | null): {
  session: CachedSession | null;
  migrated: boolean;
} {
  if (!raw) return { session: null, migrated: false };
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { session: null, migrated: false };
  }
  if (!parsed || typeof parsed !== "object") return { session: null, migrated: false };
  const obj = parsed as Record<string, unknown>;
  if (!("v" in obj)) {
    const session = validated(obj, legacyPlan(obj.plan));
    return { session, migrated: session !== null };
  }
  // A version we don't know (e.g. written by a newer build) is not trusted: sign out.
  if (obj.v !== SESSION_CACHE_VERSION) return { session: null, migrated: false };
  return { session: validated(obj.session, currentPlan((obj.session as CachedSession | null)?.plan)), migrated: false };
}

export function serializeCachedSession(session: CachedSession): string {
  return JSON.stringify({ v: SESSION_CACHE_VERSION, session });
}
