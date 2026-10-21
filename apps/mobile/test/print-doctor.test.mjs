import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const screen = readFileSync(new URL("../app/print-doctor/[id].tsx", import.meta.url), "utf8");
const printers = readFileSync(new URL("../app/printers.tsx", import.meta.url), "utf8");

test("reference 57 is reachable from a concrete mobile printer profile", () => {
  assert.match(printers, /router\.push\(`\/print-doctor\/\$\{profile\.id\}`\)/);
  assert.match(screen, /AI Print Doctor/);
});

test("print doctor previews bounded rules before explicit apply", () => {
  assert.match(screen, /client\.reportPrint\(profile\.id, \{/);
  assert.match(screen, /apply: false/);
  assert.match(screen, /apply: true/);
  assert.match(screen, /Предпросмотр рекомендаций/);
  assert.match(screen, /Применить к следующей печати/);
});

test("photo diagnosis uses real uploads and terminal job state", () => {
  assert.match(screen, /uploadPhoto\(client, session\.workspaceId, photo\)/);
  assert.match(screen, /client\.reportPrintPhotos\(profile\.id, \{/);
  assert.match(screen, /client\.waitForJob\(accepted\.job_id\)/);
  assert.match(screen, /job\.status !== "succeeded"/);
  assert.match(screen, /confidence >= 0\.5/);
});

test("provider-off state falls back to manual symptoms without fake localisation", () => {
  assert.match(screen, /photo_diagnosis_not_enabled/);
  assert.match(screen, /Выберите видимые дефекты вручную/);
  assert.match(screen, /точной рамки дефекта и автоматического измерения пока нет/);
  assert.match(screen, /Текущую деталь, модель или уже созданный G-code они не исправляют/);
});
