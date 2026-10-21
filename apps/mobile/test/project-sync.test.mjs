import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 61 reports actual server and live-room state", () => {
  assert.match(project, /client\.liveRoom\(id,[\s\S]*setLiveConnected\)/);
  assert.match(project, /project\?\.updated_at/);
  assert.match(project, /Live-связь с сервером активна/);
  assert.match(project, /Проект загружен с сервера; live-связь сейчас недоступна/);
});

test("sync card identifies only the current device and states the missing boundary", () => {
  assert.match(project, /Platform\.OS === "ios"/);
  assert.match(project, /Список других устройств и общий offline-очередь пока не отслеживаются/);
  assert.doesNotMatch(project, /Все изменения сохранены на всех устройствах/);
});
