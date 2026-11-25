import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { studioCatalogActions } from "../src/studio-tool-catalog.ts";

test("reference 50 exposes every existing mobile workspace action once", () => {
  const actions = studioCatalogActions({ modelAvailable: true, activeAvailable: true });
  assert.equal(actions.length, 10);
  assert.equal(new Set(actions.map((action) => action.id)).size, actions.length);
  assert.deepEqual(actions.map((action) => action.id), [
    "select", "paint", "mesh", "dimensions", "grid", "layers",
    "properties", "check", "versions", "export",
  ]);
  assert.equal(actions.every((action) => !action.disabled), true);
});

test("catalog keeps unavailable tools visible and fail-closed", () => {
  const empty = studioCatalogActions({ modelAvailable: false, activeAvailable: false });
  assert.equal(empty.every((action) => action.disabled), true);
  const impossibleModelOnly = studioCatalogActions({ modelAvailable: true, activeAvailable: false });
  assert.deepEqual(
    impossibleModelOnly.filter((action) => !action.disabled).map((action) => action.id),
    ["select", "paint", "mesh", "dimensions", "grid"],
  );
  const versionOnly = studioCatalogActions({ modelAvailable: false, activeAvailable: true });
  assert.deepEqual(
    versionOnly.filter((action) => !action.disabled).map((action) => action.id),
    ["layers", "properties", "check", "versions", "export"],
  );
});

test("workspace catalogue only dispatches existing panels and never starts a job", () => {
  const shell = readFileSync(new URL("../src/WorkspaceShell.tsx", import.meta.url), "utf8");
  const catalog = readFileSync(new URL("../src/StudioToolCatalog.tsx", import.meta.url), "utf8");
  assert.match(shell, /<StudioToolCatalog/);
  assert.match(shell, /setToolCatalogOpen\(true\)/);
  assert.match(shell, /accessibilityState=\{\{ expanded: toolCatalogOpen \}\}/);
  assert.match(shell, /if \(action\.target\.kind === "tool"\) onTool/);
  assert.match(shell, /else if \(action\.target\.kind === "tab"\) onTabChange/);
  assert.match(shell, /else onExport\(\)/);
  assert.match(catalog, /No job starts until you explicitly apply/);
  assert.match(catalog, /accessibilityViewIsModal/);
  assert.match(catalog, /accessibilityRole="header"/);
  assert.doesNotMatch(catalog, /PhysicalAiClient|waitForJob|compose|enqueue|fetch\(/);
});
