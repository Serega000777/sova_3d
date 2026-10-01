/** The library view: search, sort and filter behave the same on every client. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { isDraft, libraryView, matchesQuery, relativeTime } from "../src/library.ts";

const items = [
  { id: "a", name: "Корпус для платы", head_version_id: "v1", created_at: "2026-09-01T10:00:00Z", updated_at: "2026-09-20T10:00:00Z" },
  { id: "b", name: "Скан комнаты 2", head_version_id: null, created_at: "2026-09-25T10:00:00Z", updated_at: "2026-09-25T10:00:00Z" },
  { id: "c", name: "Скан комнаты 10", description: "кухня и коридор", head_version_id: "v3", created_at: "2026-09-10T10:00:00Z", updated_at: null },
  { id: "d", name: "Ключ", head_version_id: "v4", created_at: "2026-09-28T10:00:00Z", updated_at: "2026-09-29T10:00:00Z" },
];

const ids = (list: { id: string }[]) => list.map((i) => i.id).join("");

test("a project without a version is a draft", () => {
  assert.equal(isDraft(items[1]!), true);
  assert.equal(isDraft(items[0]!), false);
});

test("the default view is newest-updated first and keeps everything", () => {
  assert.equal(ids(libraryView(items)), "dbac");
});

test("sorting by creation date and by name (numbers in natural order)", () => {
  assert.equal(ids(libraryView(items, { sort: "created" })), "dbca");
  const names = libraryView(items, { sort: "name" }).map((i) => i.name);
  assert.ok(names.indexOf("Скан комнаты 2") < names.indexOf("Скан комнаты 10"), "2 comes before 10");
});

test("the model and draft filters split the library", () => {
  assert.equal(ids(libraryView(items, { filter: "models" })), "dac");
  assert.equal(ids(libraryView(items, { filter: "drafts" })), "b");
});

test("search needs every word and also looks in the description", () => {
  assert.equal(ids(libraryView(items, { query: "скан комнаты" })), "bc");
  assert.equal(ids(libraryView(items, { query: "КУХНЯ" })), "c");
  assert.equal(ids(libraryView(items, { query: "скан ключ" })), "");
  assert.equal(matchesQuery(items[0]!, "   "), true);
});

test("search, filter and sort compose without changing the input", () => {
  const before = JSON.stringify(items);
  assert.equal(ids(libraryView(items, { query: "скан", filter: "models" })), "c");
  assert.equal(JSON.stringify(items), before);
});

test("relative time reads naturally in both languages", () => {
  const now = Date.parse("2026-10-01T12:00:00Z");
  assert.equal(relativeTime("2026-10-01T11:59:40Z", now, "ru"), "только что");
  assert.equal(relativeTime("2026-10-01T11:30:00Z", now, "ru"), "30 мин назад");
  assert.equal(relativeTime("2026-10-01T09:00:00Z", now, "en"), "3 h ago");
  assert.equal(relativeTime("2026-09-29T12:00:00Z", now, "ru"), "2 дн. назад");
  assert.equal(relativeTime("garbage", now, "en"), "");
});
