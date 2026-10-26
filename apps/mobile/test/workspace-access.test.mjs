import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const access = readFileSync(new URL("../app/workspace-access.tsx", import.meta.url), "utf8");
const profile = readFileSync(new URL("../app/(tabs)/profile.tsx", import.meta.url), "utf8");

test("reference 62 reaches owner-managed team workspace access", () => {
  assert.match(profile, /router\.push\("\/workspace-access"\)/);
  assert.match(access, /client\.me\(\)/);
  assert.match(access, /current\?\.kind === "team" && current\.role === "owner"/);
  assert.match(access, /listWorkspaceMembers/);
  assert.match(access, /addWorkspaceMember/);
  assert.match(access, /updateWorkspaceMember/);
  assert.match(access, /removeWorkspaceMember/);
});

test("personal, non-owner and owner membership boundaries stay explicit", () => {
  assert.match(access, /Личное пространство нельзя расшарить/);
  assert.match(access, /только владелец team workspace/);
  assert.match(access, /member\.role === "owner"/);
  assert.match(access, /доступ владельца неизменяем/);
  assert.match(access, /Добавить зарегистрированного пользователя/);
});
