import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/settings/page.tsx", import.meta.url), "utf8");

test("settings creates, shows once, lists and revokes developer API keys", () => {
  assert.match(page, /client\.listDeveloperTokens/);
  assert.match(page, /client\.createDeveloperToken/);
  assert.match(page, /createdSecret/);
  assert.match(page, /повторно показать его нельзя/);
  assert.match(page, /client\.revokeDeveloperToken/);
});
