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

test("O10 keeps visible and accessible tool labels in the selected language", () => {
  assert.match(shell, /label: \{ ru: "Краска", en: "Paint" \}/);
  assert.match(shell, /label: \{ ru: "Правка", en: "Edit" \}/);
  assert.match(shell, /accessibilityLabel=\{tool\.label\[language\]\}/);
  assert.match(shell, /\{tool\.label\[language\]\}/);
  assert.match(shell, /\{item\.label\[language\]\}/);
  assert.match(project, /language=\{language\}/);
});

test("G01 switches the actual Three.js canvas between dark and light green presets", () => {
  const viewer = readFileSync(new URL("../src/ModelViewer.tsx", import.meta.url), "utf8");
  assert.match(shell, /accessibilityLabel=\{language === "ru" \? "Светлое полотно моделирования"/);
  assert.match(shell, /onCanvasThemeChange\(canvasTheme === "light" \? "dark" : "light"\)/);
  assert.match(project, /canvasTheme=\{viewerCanvasTheme\}/);
  assert.match(viewer, /light: \{ background: "#f4f3ed", centerLine: 0x527462, gridLine: 0xc9d1ca/);
  assert.match(viewer, /current\.renderer\.setClearColor\(palette\.background, 1\)/);
  assert.match(viewer, /current\.scene\.background = new THREE\.Color\(palette\.background\)/);
  assert.match(viewer, /const nextGrid = makeModellingGrid\(canvasTheme, showGrid\)/);
});
