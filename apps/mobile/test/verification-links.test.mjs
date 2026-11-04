import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  verificationLinkPageUrl,
  verificationLinkState,
} from "../src/verification-links.ts";

test("verification page URL prefers production web origin and maps LAN API to web port", () => {
  assert.equal(
    verificationLinkPageUrl({
      token: "vrf_abcdefghijklmnop",
      apiBaseUrl: "https://api.sova.example/api/v1",
      webBaseUrl: "https://app.sova.example/somewhere",
    }),
    "https://app.sova.example/verify/vrf_abcdefghijklmnop",
  );
  assert.equal(
    verificationLinkPageUrl({
      token: "vrf_abcdefghijklmnop",
      apiBaseUrl: "http://192.168.1.20:18000/api/v1",
      webBaseUrl: "http://localhost:3100",
    }),
    "http://192.168.1.20:3100/verify/vrf_abcdefghijklmnop",
  );
  assert.throws(
    () => verificationLinkPageUrl({ token: "shr_wrong", apiBaseUrl: "https://api.sova.example" }),
    /invalid verification token/,
  );
});

test("verification link status is fail-closed for revoked, expired and malformed dates", () => {
  const active = {
    id: "link",
    created_at: "2026-11-01T00:00:00Z",
    expires_at: "2026-11-10T00:00:00Z",
    revoked_at: null,
    last_used_at: null,
  };
  const now = Date.parse("2026-11-04T00:00:00Z");
  assert.equal(verificationLinkState(active, now), "active");
  assert.equal(verificationLinkState({ ...active, expires_at: "2026-11-03T00:00:00Z" }, now), "expired");
  assert.equal(verificationLinkState({ ...active, expires_at: "bad" }, now), "expired");
  assert.equal(verificationLinkState({ ...active, revoked_at: "2026-11-02T00:00:00Z" }, now), "revoked");
});

test("references 90 and 97 reach owner-only create, list, revoke and native share", () => {
  const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
  const passport = readFileSync(new URL("../src/ModelPassportSheet.tsx", import.meta.url), "utf8");
  const card = readFileSync(new URL("../src/IntegrityVerificationLinksCard.tsx", import.meta.url), "utf8");

  assert.match(project, /activeModelCheck && canManageShareLinks/);
  assert.match(project, /<IntegrityVerificationLinksCard/);
  assert.match(passport, /onOpenVerificationLinks/);
  assert.match(project, /onOpenVerificationLinks=\{canManageShareLinks/);
  assert.match(passport, /Публичная ссылка проверки/);
  assert.match(card, /client\.createVerificationLink\(sourceVersionId/);
  assert.match(card, /client\.listVerificationLinks\(sourceVersionId\)/);
  assert.match(card, /client\.revokeVerificationLink\(sourceVersionId, linkId\)/);
  assert.match(card, /versionIdRef\.current === sourceVersionId/);
  assert.match(card, /await Share\.share/);
  assert.match(card, /await Share\.share\([\s\S]*?const next = await client\.listVerificationLinks\(sourceVersionId\);[\s\S]*?if \(versionIdRef\.current === sourceVersionId\) setLinks\(next\);/);
  assert.match(card, /Секрет показывается только сейчас и не сохраняется/);
});
