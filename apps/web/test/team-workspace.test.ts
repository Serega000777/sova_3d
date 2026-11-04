import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/team/page.tsx", import.meta.url), "utf8");
const settings = readFileSync(new URL("../src/app/settings/page.tsx", import.meta.url), "utf8");

test("team dashboard loads canonical members, tasks, and activity for the selected scope", () => {
  assert.match(page, /const workspaceId = session\.workspaceId/);
  assert.match(page, /client\.listWorkspaceMembers\(workspaceId\)/);
  assert.match(page, /client\.listWorkspaceTasks\(workspaceId\)/);
  assert.match(page, /client\.listWorkspaceVersionActivity\(workspaceId, 12\)/);
  assert.match(page, /loadRevision\.current !== request \|\| session\.workspaceId !== workspaceId/);
});

test("activity failure remains local and does not hide the team task list", () => {
  assert.match(page, /\.catch\(\(reason: unknown\) => \(\{/);
  assert.match(page, /setActivityError\(activityResult\.error\)/);
  assert.match(page, /activityError && \(/);
  assert.match(page, /tasks\.map\(\(task\) =>/);
});

test("team task writes preserve server CAS and role boundaries", () => {
  assert.match(page, /workspace\.role !== "viewer"/);
  assert.match(page, /expected_revision: task\.revision/);
  assert.match(page, /completed: !task\.completed/);
  assert.match(page, /disabled=\{!tasksManageable \|\| Boolean\(busy\)\}/);
});

test("settings links to the dashboard only for the selected team workspace", () => {
  assert.match(settings, /workspace\.id === session\.workspaceId && workspace\.kind === "team"/);
  assert.match(settings, /href="\/team"/);
});
