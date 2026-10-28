import assert from "node:assert/strict";
import test from "node:test";

import {
  LEGACY_SESSION_KEY,
  SECURE_SESSION_KEY,
  parseStoredSession,
  readStoredSession,
  removeStoredSession,
  writeStoredSession,
} from "../src/session-storage.ts";

function memoryStore(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    values,
    async getItem(key) {
      return values.get(key) ?? null;
    },
    async setItem(key, value) {
      values.set(key, value);
    },
    async removeItem(key) {
      values.delete(key);
    },
  };
}

const session = {
  baseUrl: "https://api.sova.test",
  token: "secret-token",
  workspaceId: "workspace-1",
  displayName: "Sova",
  address: "sova@example.test",
};

test("stored sessions are parsed fail-closed", () => {
  assert.deepEqual(parseStoredSession(JSON.stringify(session)), session);
  assert.equal(parseStoredSession("not-json"), null);
  assert.equal(parseStoredSession(JSON.stringify({ ...session, token: "" })), null);
  assert.equal(parseStoredSession(JSON.stringify({ ...session, address: 42 })), null);
});

test("a legacy AsyncStorage session migrates after the secure write", async () => {
  const legacy = memoryStore({ [LEGACY_SESSION_KEY]: JSON.stringify(session) });
  const secure = memoryStore();

  assert.deepEqual(await readStoredSession(secure, legacy), session);
  assert.equal(legacy.values.has(LEGACY_SESSION_KEY), false);
  assert.deepEqual(
    JSON.parse(secure.values.get(SECURE_SESSION_KEY)),
    session,
  );
});

test("a failed secure write leaves the legacy session available for a later migration", async () => {
  const legacy = memoryStore({ [LEGACY_SESSION_KEY]: JSON.stringify(session) });
  const secure = memoryStore();
  secure.setItem = async () => {
    throw new Error("secure store unavailable");
  };

  await assert.rejects(() => readStoredSession(secure, legacy), /secure store unavailable/);
  assert.equal(legacy.values.has(LEGACY_SESSION_KEY), true);
});

test("a corrupt secure value and stale legacy token are both deleted", async () => {
  const secure = memoryStore({ [SECURE_SESSION_KEY]: "corrupt" });
  const legacy = memoryStore({ [LEGACY_SESSION_KEY]: JSON.stringify(session) });

  assert.equal(await readStoredSession(secure, legacy), null);
  assert.equal(secure.values.has(SECURE_SESSION_KEY), false);
  assert.equal(legacy.values.has(LEGACY_SESSION_KEY), false);
});

test("write and sign-out remove the plaintext legacy copy", async () => {
  const secure = memoryStore();
  const legacy = memoryStore({ [LEGACY_SESSION_KEY]: JSON.stringify(session) });

  await writeStoredSession(secure, session, legacy);
  assert.equal(legacy.values.has(LEGACY_SESSION_KEY), false);
  assert.equal(secure.values.has(SECURE_SESSION_KEY), true);

  await removeStoredSession(secure, legacy);
  assert.equal(secure.values.has(SECURE_SESSION_KEY), false);
});
