import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Sova centre continues the real most recently updated project without invented progress", () => {
  const source = readFileSync(new URL("../app/(tabs)/index.tsx", import.meta.url), "utf8");

  assert.match(source, /libraryView\(projects, \{ query: "", filter: "all", sort: "updated" \}\)/);
  assert.match(source, /const continueProject = recentProjects\[0\] \?\? null/);
  assert.match(source, /Продолжить работу/);
  assert.match(source, /href=\{`\/project\/\$\{continueProject\.id\}`\}/);
  assert.match(source, /continueProject\.head_version_id \? "Последняя сохранённая модель" : "Черновик без модели"/);
  assert.doesNotMatch(source, /82%|процент готовности|готово на/);
});

test("reference 100 links canonical favorites and completed purchases from the centre", () => {
  const source = readFileSync(new URL("../app/(tabs)/index.tsx", import.meta.url), "utf8");
  const collections = readFileSync(new URL("../app/collections.tsx", import.meta.url), "utf8");

  assert.match(source, /client\.favoriteListings\(\)/);
  assert.match(source, /client\.myOrders\(\)/);
  assert.match(source, /router\.push\("\/collections"\)/);
  assert.match(source, /Моя библиотека/);
  assert.match(collections, /client\.orderFiles\(order\.id\)/);
  assert.match(collections, /client\.download\(file\.asset_id\)/);
  assert.match(collections, /verifiedMarketplaceDownloadUrl\(file, target\)/);
  assert.match(collections, /Linking\.openURL\(url\)/);
  assert.match(collections, /shareOrderSovaPackage\(client, order\.id\)/);
  assert.match(collections, /Скачать редактируемый проект \.sova/);
  assert.match(collections, /не является очередью физического производства/);
});

test("launch centre has one working hero action and no dead notification or plan promos", () => {
  const source = readFileSync(new URL("../app/(tabs)/index.tsx", import.meta.url), "utf8");

  assert.match(source, /accessibilityLabel="Создать новый проект"/);
  assert.match(source, /onPress=\{openCreate\}/);
  assert.match(source, /Начать проект/);
  assert.doesNotMatch(source, /Уведомления — скоро|Sova 3D Pro|proSoon/);
});
