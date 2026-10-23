import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const editor = readFileSync(new URL("../src/RoomWallEditor.tsx", import.meta.url), "utf8");

test("reference 21 rebuilds one selected RoomPlan wall as a new immutable version", () => {
  assert.match(project, /planSelection\?\.kind === "wall"/);
  assert.match(project, /client\.editRoomWall/);
  assert.match(project, /await headAfterJob\(job\)/);
  assert.match(editor, /Смещение переносит стену параллельно/);
  assert.match(editor, /thicknessMm/);
  assert.match(editor, /heightMm/);
  assert.match(editor, /material\.tabs\.includes\("wall"\)/);
  assert.match(editor, /Перестроить комнату/);
});
