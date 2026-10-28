import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const profileUrl = new URL("../app/(tabs)/profile.tsx", import.meta.url);
const legalUrl = new URL("../app/legal.tsx", import.meta.url);

test("profile exposes an in-app destructive account deletion path", async () => {
  const source = await readFile(profileUrl, "utf8");
  assert.match(source, /client\.deleteAccount\(\)/);
  assert.match(source, /Удалить аккаунт/);
  assert.match(source, /30 дней/);
  assert.match(source, /style: "destructive"/);
});

test("privacy and terms are available from the signed-in app", async () => {
  const [profile, legal] = await Promise.all([
    readFile(profileUrl, "utf8"),
    readFile(legalUrl, "utf8"),
  ]);
  assert.match(profile, /router\.push\("\/legal"\)/);
  assert.match(legal, /Обучение и хранение/);
  assert.match(legal, /Условия использования/);
  assert.match(legal, /Удаление аккаунта/);
});
