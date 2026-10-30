import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/slicer/page.tsx", import.meta.url), "utf8");

test("slicer exposes and sends automatic or painted-only support generation", () => {
  assert.match(page, /supportGenerationMode/);
  assert.match(page, /support_generation_mode: supportGenerationMode/);
  assert.match(page, /Создание поддержек:/);
  assert.match(page, /Автоматически/);
  assert.match(page, /Только нарисованные/);
  assert.match(page, /setSupportGenerationMode\("painted_only"\)/);
  assert.match(page, /if \(!event\.target\.checked\) \{\s*setSupportGenerationMode\("auto"\)/);
  assert.ok(
    page.includes('<div className="row" role="group" aria-label="Режим создания поддержек">'),
  );
  assert.ok(page.includes('aria-pressed={supportGenerationMode === "auto"}'));
  assert.ok(page.includes('aria-pressed={supportGenerationMode === "painted_only"}'));
});
