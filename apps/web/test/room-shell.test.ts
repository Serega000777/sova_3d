import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("web scan result exposes the exact RoomPlan empty-room artifact", () => {
  const page = readFileSync(
    new URL("../src/app/scanner/[id]/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(page, /current\.room_shell_asset_id/);
  assert.match(page, /setShowEmptyRoom\(true\)/);
  assert.match(page, /Пустая комната/);
  assert.match(page, /showEmptyRoom \? roomShellUrl : modelUrl/);
  assert.match(page, /Размеры оболочки комнаты/);
  assert.match(page, /это не AI-очистка фотосканирования/);
});
