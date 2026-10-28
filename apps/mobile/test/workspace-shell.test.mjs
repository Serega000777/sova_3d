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

test("O02 gives the model reversible space without discarding editor state", () => {
  assert.match(shell, /accessibilityLabel=\{modelFocused \? "Вернуть панели редактора" : "Больше места для модели"\}/);
  assert.match(shell, /!modelFocused && \(\s*<View style=\{\{ width: 96/);
  assert.match(shell, /!modelFocused && \(\s*<View style=\{\{ width: 318/);
  assert.match(shell, /!modelFocused && toolbar/);
  assert.match(shell, /onModelFocusChange\?\.\(modelFocused\)/);
  assert.match(project, /height=\{workspaceModelFocused \? \(isTablet \? 680 : 520\) : isTablet \? 520 : 360\}/);
  assert.match(project, /onModelFocusChange=\{setWorkspaceModelFocused\}/);
});
