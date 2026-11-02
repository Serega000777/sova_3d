import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { projectShareLinkState, projectSharePageUrl } from "../src/project-share-links.ts";

test("mobile share URL uses explicit production web origin", () => {
  assert.equal(
    projectSharePageUrl({
      token: "shr_abcdefghijklmnopqrstuvwxyz",
      apiBaseUrl: "https://api.sova.example",
      webBaseUrl: "https://sova.example/stale/path?ignored=yes",
    }),
    "https://sova.example/shared/shr_abcdefghijklmnopqrstuvwxyz",
  );
});

test("mobile share URL maps API host to the LAN web server instead of localhost", () => {
  assert.equal(
    projectSharePageUrl({
      token: "shr_abcdefghijklmnopqrstuvwxyz",
      apiBaseUrl: "http://192.168.1.50:18000",
      webBaseUrl: "http://localhost:3100",
    }),
    "http://192.168.1.50:3100/shared/shr_abcdefghijklmnopqrstuvwxyz",
  );
  assert.throws(() => projectSharePageUrl({ token: "bad", apiBaseUrl: "http://localhost:18000" }));
});

test("share-link state is fail-closed for revoked and expired links", () => {
  const base = {
    id: "00000000-0000-0000-0000-000000000001",
    created_at: "2026-11-01T00:00:00Z",
    expires_at: "2026-11-03T00:00:00Z",
    revoked_at: null,
    last_used_at: null,
  };
  assert.equal(projectShareLinkState(base, Date.parse("2026-11-02T00:00:00Z")), "active");
  assert.equal(projectShareLinkState(base, Date.parse("2026-11-04T00:00:00Z")), "expired");
  assert.equal(projectShareLinkState({ ...base, revoked_at: "2026-11-01T12:00:00Z" }, 0), "revoked");
  assert.equal(projectShareLinkState({ ...base, expires_at: "not-a-date" }, 0), "expired");
});

test("project screen exposes owner-only create/list/revoke through the system share sheet", () => {
  const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
  const card = readFileSync(new URL("../src/ProjectShareLinksCard.tsx", import.meta.url), "utf8");
  assert.match(project, /setCanManageShareLinks\(current\?\.role === "owner"\)/);
  assert.match(project, /canManageShareLinks \? \(/);
  assert.match(card, /client\.createProjectShareLink\(projectId/);
  assert.match(card, /client\.listProjectShareLinks\(projectId\)/);
  assert.match(card, /client\.revokeProjectShareLink\(projectId, linkId\)/);
  assert.match(card, /Share\.share\(\{/);
  assert.match(card, /Секрет показывается один раз/);
});
