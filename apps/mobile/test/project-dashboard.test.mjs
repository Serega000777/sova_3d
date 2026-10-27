import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { projectDashboardState } from "../src/project-dashboard.ts";

test("project dashboard reports only observable project evidence", () => {
  assert.deepEqual(
    projectDashboardState({ hasModel: true, versionCount: 4, checkState: "warning", participantCount: 3 }),
    {
      modelLabel: "Модель создана",
      checkLabel: "Есть замечания проверки",
      versionLabel: "4 версии",
      participantLabel: "3 участника",
    },
  );
  assert.equal(
    projectDashboardState({ hasModel: false, versionCount: -3, checkState: "not_run", participantCount: null }).versionLabel,
    "0 версий",
  );
  assert.equal(
    projectDashboardState({ hasModel: true, versionCount: 21, checkState: "passed", participantCount: 22 }).participantLabel,
    "22 участника",
  );
});

test("mobile project route wires the dashboard to real project actions", () => {
  const source = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
  assert.match(source, /<ProjectDashboardCard/);
  assert.match(source, /versionCount=\{versionHistory\.length\}/);
  assert.match(source, /updatedAt=\{project\?\.updated_at \?\? null\}/);
  assert.match(source, /participantCount=\{workspaceParticipantCount\}/);
  assert.match(source, /listWorkspaceMembers\(session\.workspaceId\)/);
  assert.match(source, /onCheck=\{\(\) => setWorkspaceTab\("check"\)\}/);
  assert.match(source, /onVersions=\{\(\) => router\.push\(`\/project-history\/\$\{id\}`\)\}/);
  assert.match(source, /onExport=\{\(\) => setWorkspaceTab\("export"\)\}/);
});
