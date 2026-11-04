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

test("settings always links to the team dashboard so personal users can create a team", () => {
  assert.match(settings, /href="\/team"/);
});

test("personal workspace can create a server team and switches scope only after success", () => {
  assert.match(page, /client\.createTeamWorkspace\(\{ name: workspaceName\.trim\(\) \}\)/);
  assert.match(page, /signIn\(\{ \.\.\.session, workspaceId: created\.id \}\)/);
  assert.match(page, /workspace\?\.kind !== "team"/);
});

test("only an owner receives member mutations and the immutable owner has no controls", () => {
  assert.match(page, /workspace\?\.role !== "owner"/);
  assert.match(page, /client\.addWorkspaceMember\(session\.workspaceId/);
  assert.match(page, /client\.updateWorkspaceMember\(session\.workspaceId, member\.user_id, role\)/);
  assert.match(page, /client\.removeWorkspaceMember\(session\.workspaceId, member\.user_id\)/);
  assert.match(page, /workspace\.role === "owner" && member\.role !== "owner"/);
  assert.match(page, /window\.confirm/);
});
