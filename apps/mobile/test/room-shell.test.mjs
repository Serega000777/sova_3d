import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("mobile scan result switches to the exact RoomPlan empty-room artifact", () => {
  const page = readFileSync(new URL("../app/scan/[id].tsx", import.meta.url), "utf8");

  assert.match(page, /scan\?\.room_shell_asset_id/);
  assert.match(page, /setPreviewMode\("empty"\)/);
  assert.match(page, /Показать пустую оболочку RoomPlan/);
  assert.match(page, /previewMode === "empty" \? roomShellUrl : modelUrl/);
  assert.match(page, /Размеры оболочки комнаты/);
  assert.match(page, /без мебели и деталей поверхностей/);
});
