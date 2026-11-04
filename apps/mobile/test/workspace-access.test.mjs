import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const access = readFileSync(new URL("../app/workspace-access.tsx", import.meta.url), "utf8");
const profile = readFileSync(new URL("../app/(tabs)/profile.tsx", import.meta.url), "utf8");

test("references 62 and 64 reach canonical team workspace access", () => {
  assert.match(profile, /router\.push\("\/workspace-access"\)/);
  assert.match(access, /client\.me\(\)/);
  assert.match(access, /workspace\?\.kind === "team" && workspace\.role === "owner"/);
  assert.match(access, /listWorkspaceMembers/);
  assert.match(access, /createTeamWorkspace/);
  assert.match(access, /selectWorkspace/);
  assert.match(access, /listProjects/);
  assert.match(access, /addWorkspaceMember/);
  assert.match(access, /updateWorkspaceMember/);
  assert.match(access, /removeWorkspaceMember/);
  assert.match(access, /listWorkspaceTasks/);
  assert.match(access, /listWorkspaceVersionActivity\(workspaceId, 12\)/);
  assert.match(access, /createWorkspaceTask/);
  assert.match(access, /updateWorkspaceTask/);
});

test("creation, selection and owner-only mutation boundaries stay explicit", () => {
  assert.match(access, /Создать team workspace/);
  assert.match(access, /Состав команды доступен всем участникам; роли меняет только владелец/);
  assert.match(access, /member\.role === "owner"/);
  assert.match(access, /Добавить зарегистрированного пользователя/);
  assert.match(access, /openTaskCount \?\? "—"/);
  assert.match(access, /expected_revision: task\.revision/);
  assert.match(access, /workspace\.role !== "viewer"/);
  assert.match(access, /accessibilityRole="checkbox"/);
  assert.match(access, /loadRevision\.current !== request/);
  assert.match(access, /Активность команды/);
  assert.match(access, /Финализированные immutable-версии проектов выбранного workspace/);
  assert.match(access, /router\.push\(`\/project\/\$\{item\.project_id\}`\)/);
  assert.match(access, /Лента версий недоступна/);
});
