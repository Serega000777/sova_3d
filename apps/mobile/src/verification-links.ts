import type { VerificationLinkOut } from "@physical-ai/contracts";

export type VerificationLinkState = "active" | "expired" | "revoked";

function isLoopback(url: URL): boolean {
  return url.hostname === "localhost" || url.hostname === "127.0.0.1" || url.hostname === "::1";
}

function normalizedOrigin(value: string): URL {
  const parsed = new URL(value);
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("verification URL must use HTTP or HTTPS");
  }
  parsed.pathname = "/";
  parsed.search = "";
  parsed.hash = "";
  return parsed;
}

/** Build the public report page URL while keeping the one-time secret in transient state only. */
export function verificationLinkPageUrl({
  token,
  apiBaseUrl,
  webBaseUrl,
}: {
  token: string;
  apiBaseUrl: string;
  webBaseUrl?: string | null;
}): string {
  if (!/^vrf_[A-Za-z0-9_-]{16,}$/.test(token)) throw new Error("invalid verification token");
  const api = normalizedOrigin(apiBaseUrl);
  let web: URL | null = null;
  if (webBaseUrl) {
    try {
      const configured = normalizedOrigin(webBaseUrl);
      if (!isLoopback(configured) || isLoopback(api)) web = configured;
    } catch {
      // A bad optional web override must not hide the already-created one-time secret.
    }
  }
  if (!web) {
    web = new URL(api.toString());
    if (web.port === "18000") web.port = "3100";
  }
  return new URL(`/verify/${encodeURIComponent(token)}`, web).toString();
}

export function verificationLinkState(
  link: VerificationLinkOut,
  nowMs = Date.now(),
): VerificationLinkState {
  if (link.revoked_at) return "revoked";
  const expiresMs = Date.parse(link.expires_at);
  return Number.isFinite(expiresMs) && expiresMs > nowMs ? "active" : "expired";
}
