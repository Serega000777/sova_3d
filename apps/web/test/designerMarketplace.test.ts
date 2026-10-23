import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const market = readFileSync(new URL("../src/app/market/page.tsx", import.meta.url), "utf8");
const gallery = readFileSync(new URL("../src/components/TemplateGallery.tsx", import.meta.url), "utf8");

test("specialist template marketplace uses the real template API and exact project start", () => {
  assert.match(market, /client\.listTemplates\(\)/);
  assert.match(market, /client\.startFromTemplate\(/);
  assert.match(market, /workspace_id: session\.workspaceId/);
  assert.match(market, /template_id: template\.id/);
  assert.match(market, /filterByCategory/);
  assert.match(market, /Проверенные специализированные шаблоны/);
});

test("template niches filter the buildable catalogue rather than decorative cards", () => {
  assert.match(gallery, /new Set\(templates\.map\(\(template\) => template\.category\)\)/);
  assert.match(gallery, /templates\.filter\(\(template\) => template\.category === category\)/);
  assert.match(gallery, /onStart\(template, params\)/);
  assert.match(gallery, /Ниши шаблонов/);
});
