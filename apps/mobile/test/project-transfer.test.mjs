import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { ApiError } from "@physical-ai/contracts";

import { projectTransferError, projectTransferRequest } from "../src/project-transfer.ts";

test("project transfer normalizes email and requires the exact project name", () => {
  assert.deepEqual(projectTransferRequest("  NEW.Owner@Example.COM ", "Дом", "Дом"), {
    body: { recipient_email: "new.owner@example.com", confirmation_name: "Дом" },
    error: null,
  });
  assert.equal(projectTransferRequest("not-an-email", "Дом", "Дом").body, null);
  assert.equal(projectTransferRequest("owner@example.com", " Дом ", "Дом").body, null);
  assert.equal(projectTransferRequest("", "Дом", "Дом").body, null);
});

test("project transfer API errors do not reveal recipient details", () => {
  const privateMessage = "the recipient secret@example.com is unavailable";
  for (const status of [404, 409, 422]) {
    const message = projectTransferError(new ApiError(status, "transfer_failed", privateMessage, {}, "trace"));
    assert.doesNotMatch(message, /secret@example\.com|recipient/i);
  }
  assert.doesNotMatch(projectTransferError(new Error(privateMessage)), /secret@example\.com|recipient/i);
});

test("project screen exposes the transfer only through the owner-only branch", () => {
  const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
  const card = readFileSync(new URL("../src/ProjectTransferCard.tsx", import.meta.url), "utf8");
  assert.match(project, /item\.id === projectWorkspaceId/);
  assert.match(project, /setCanManageShareLinks\(false\);[\s\S]*client\.me\(\)/);
  assert.match(project, /setCanManageShareLinks\(current\?\.role === "owner"\)/);
  assert.match(project, /canManageShareLinks \? \(/);
  assert.match(project, /<ProjectTransferCard/);
  assert.match(project, /router\.replace\("\/projects"\)/);
  assert.match(card, /client\.transferProject\(projectId, body\)/);
  assert.match(card, /transferInFlight\.current/);
  assert.match(card, /disabled=\{busy\}/);
  assert.match(card, /Передать проект навсегда\?/);
  assert.match(card, /Отменить передачу после завершения нельзя/);
});
