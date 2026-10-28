import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const shell = readFileSync(new URL("../src/WorkspaceShell.tsx", import.meta.url), "utf8");
const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("O01 keeps export reachable from the responsive workspace header", () => {
  assert.match(shell, /accessibilityLabel="Экспортировать проект"/);
  assert.match(shell, /onPress=\{onExport\}/);
  assert.match(shell, /isTablet \? "Экспорт" : "⇧"/);
  assert.match(project, /onExport=\{\(\) => setWorkspaceTab\("export"\)\}/);
  assert.match(shell, /versionLabel \? `\$\{versionLabel\} · сохранено` : "Новая модель"/);
});
