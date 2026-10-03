import assert from "node:assert/strict";
import test from "node:test";

import {
  parseCachedSession,
  SESSION_CACHE_VERSION,
  serializeCachedSession,
} from "../src/lib/sessionCache.ts";

const base = { baseUrl: "http://api", token: "t", workspaceId: "w" };

test("legacy unversioned 'pro' (old basic tier) migrates to free, not paid", () => {
  const { session, migrated } = parseCachedSession(JSON.stringify({ ...base, plan: "pro" }));
  assert.equal(session?.plan, "free");
  assert.equal(migrated, true);
});

test("legacy unversioned 'profi' (old paid tier) migrates to pro", () => {
  const { session, migrated } = parseCachedSession(JSON.stringify({ ...base, plan: "profi" }));
  assert.equal(session?.plan, "pro");
  assert.equal(migrated, true);
});

test("legacy entry without a plan stays plan-less (treated as free) and is upgraded", () => {
  const { session, migrated } = parseCachedSession(JSON.stringify(base));
  assert.equal(session?.plan, undefined);
  assert.equal(migrated, true);
});

test("a session saved under the new schema keeps 'pro' as paid, across reloads", () => {
  const stored = serializeCachedSession({ ...base, plan: "pro" });
  assert.equal(JSON.parse(stored).v, SESSION_CACHE_VERSION);
  const first = parseCachedSession(stored);
  assert.equal(first.session?.plan, "pro");
  assert.equal(first.migrated, false);
  // a migrated legacy basic entry, once rewritten, must not be remapped again
  const migrated = parseCachedSession(JSON.stringify({ ...base, plan: "pro" })).session!;
  const again = parseCachedSession(serializeCachedSession(migrated));
  assert.equal(again.session?.plan, "free");
});

test("new-schema 'free' round-trips and keeps other fields", () => {
  const s = { ...base, plan: "free" as const, displayName: "A", address: "a@b.c" };
  assert.deepEqual(parseCachedSession(serializeCachedSession(s)).session, s);
});

test("absent, corrupt, incomplete, unknown-version and unknown-plan entries are safe", () => {
  assert.equal(parseCachedSession(null).session, null);
  assert.equal(parseCachedSession("").session, null);
  assert.equal(parseCachedSession("{not json").session, null);
  assert.equal(parseCachedSession("null").session, null);
  assert.equal(parseCachedSession("42").session, null);
  assert.equal(parseCachedSession(JSON.stringify({ baseUrl: "x" })).session, null);
  assert.equal(parseCachedSession(JSON.stringify({ v: 2, session: { baseUrl: "x" } })).session, null);
  assert.equal(parseCachedSession(JSON.stringify({ v: 99, session: base })).session, null);
  assert.equal(parseCachedSession(JSON.stringify({ ...base, plan: "gold" })).session?.plan, undefined);
  assert.equal(
    parseCachedSession(JSON.stringify({ v: 2, session: { ...base, plan: "gold" } })).session?.plan,
    undefined,
  );
});
