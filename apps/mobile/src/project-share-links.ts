import type { ShareLinkOut } from "@physical-ai/contracts";

export type ProjectShareLinkState = "active" | "expired" | "revoked";

function isLoopback(url: URL): boolean {
  return url.hostname === "localhost" || url.hostname === "127.0.0.1" || url.hostname === "::1";
}

function normalizedOrigin(value: string): URL {
  const parsed = new URL(value);
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("share URL must use HTTP or HTTPS");
  }
  parsed.pathname = "/";
  parsed.search = "";
  parsed.hash = "";
  return parsed;
}

/** Build the human-facing public page URL without ever persisting the one-time token.
 *
 * A non-loopback EXPO_PUBLIC_WEB_URL wins. During LAN development the checked-in
 * localhost value cannot work on a phone, so the API host is reused and the standard
 * web port 3100 replaces API port 18000.
 */
export function projectSharePageUrl({
  token,
  apiBaseUrl,
  webBaseUrl,
}: {
  token: string;
  apiBaseUrl: string;
  webBaseUrl?: string | null;
}): string {
  if (!/^shr_[A-Za-z0-9_-]{16,}$/.test(token)) throw new Error("invalid project share token");

  const api = normalizedOrigin(apiBaseUrl);
  let web: URL | null = null;
  if (webBaseUrl) {
    try {
      const configured = normalizedOrigin(webBaseUrl);
      if (!isLoopback(configured) || isLoopback(api)) web = configured;
    } catch {
      // A bad optional web override must not hide the already-created one-time secret.
      // Fall back to the validated API origin below.
    }
  }
  if (!web) {
    web = new URL(api.toString());
    if (web.port === "18000") web.port = "3100";
  }
  return new URL(`/shared/${encodeURIComponent(token)}`, web).toString();
}

export function projectShareLinkState(link: ShareLinkOut, nowMs = Date.now()): ProjectShareLinkState {
  if (link.revoked_at) return "revoked";
  const expiresMs = Date.parse(link.expires_at);
  return Number.isFinite(expiresMs) && expiresMs > nowMs ? "active" : "expired";
}
