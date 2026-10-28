import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const settings = readFileSync(
  new URL("../src/app/settings/page.tsx", import.meta.url),
  "utf8",
);
const publicPage = readFileSync(
  new URL("../src/app/delete-account/page.tsx", import.meta.url),
  "utf8",
);

test("settings requires explicit confirmation before requesting account deletion", () => {
  assert.match(settings, /deleteConfirmation !== "DELETE"/);
  assert.match(settings, /client\.deleteAccount\(\)/);
  assert.match(settings, /router\.push\("\/delete-account\?requested=1"\)/);
});

test("public deletion resource describes both in-app and web paths", () => {
  assert.match(publicPage, /Профиль → Удалить аккаунт/);
  assert.match(publicPage, /Settings → Delete account/);
  assert.match(publicPage, /within 30 days/);
});
