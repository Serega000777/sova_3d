import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const shell = readFileSync(new URL("../src/WorkspaceShell.tsx", import.meta.url), "utf8");
const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("O01 keeps export reachable from the responsive workspace header", () => {
  assert.match(shell, /accessibilityLabel="Экспортировать проект"/);
  assert.match(shell, /onPress=\{onExport\}/);
  assert.match(shell, /<ExportIcon color=\{colors\.text\}/);
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

test("G02 binds the properties summary to the exact selected server scene node", () => {
  assert.match(project, /sceneGraph\?\.nodes\.find\(\(node\) => node\.id === selectedSceneNodeId\)/);
  assert.match(project, /matrix\?\.length !== 4 \|\| matrix\.some\(\(row\) => row\.length !== 4\)/);
  assert.match(project, /accessibilityLabel=\{ru \? "Выбранный узел сцены"/);
  assert.match(project, /selectedSceneNode\.effective_visible/);
  assert.match(project, /selectedSceneNodePosition\[0\]\.toFixed\(2\)/);
  assert.match(project, /selectedSceneNode\.appearance\.base_color/);
  assert.match(project, /onPress=\{\(\) => setSceneTreeOpen\(true\)\}/);
});

test("G03 keeps check and version actions in the tablet workspace header", () => {
  assert.match(shell, /\{isTablet && \(/);
  assert.match(shell, /\{ id: "check", ru: "Проверка", en: "Check" \}/);
  assert.match(shell, /<CheckIcon color=\{tab === action\.id/);
  assert.match(shell, /<HistoryIcon color=\{tab === action\.id/);
  assert.match(shell, /accessibilityState=\{\{ selected: tab === action\.id \}\}/);
  assert.match(shell, /onPress=\{\(\) => onTabChange\(action\.id\)\}/);
});

test("workspace shell uses custom vectors for tools and window controls", () => {
  assert.match(shell, /<WorkspaceToolIcon id=\{tool\.id\}/);
  assert.match(shell, /<SunIcon color=\{colors\.green\}/);
  assert.match(shell, /<MoonIcon color=\{colors\.text\}/);
  assert.match(shell, /<FocusIcon color=\{modelFocused/);
  assert.match(shell, /<SwapIcon color=\{colors\.text\}/);
  assert.doesNotMatch(shell, /☀|☾|⇄|⊟|⊞|⇧/);
});

test("G04 keeps measured model dimensions visible over the viewport", () => {
  assert.match(shell, /dimensionsActive\s*\? "dimensions"/);
  assert.match(project, /setDimensionHudVisible\(\(visible\) => !visible\)/);
  assert.match(project, /\{dimensionHudVisible && size && \(/);
  assert.match(project, /accessibilityLabel=\{ru \? "Размеры объекта в миллиметрах"/);
  assert.match(project, /size\.x\.toLocaleString/);
  assert.match(project, /size\.y\.toLocaleString/);
  assert.match(project, /size\.z\.toLocaleString/);
  assert.match(project, /Общий envelope видимой сцены/);
});

test("G05 exposes only measured facts for the selected mesh component", () => {
  assert.match(project, /accessibilityLabel=\{ru \? "Выделение компонента сетки"/);
  assert.match(project, /componentSelection\.ids\.length/);
  assert.match(project, /componentSelection\.expectedFaces\.toLocaleString/);
  assert.match(project, /sceneNodeNames\.get\(componentSelection\.sceneNodeId\)/);
  assert.match(project, /componentSelection\.anchor\.at_mm\[0\]\.toFixed\(3\)/);
  assert.match(project, /componentSelection\.anchor\.normal\.map/);
  assert.match(project, /setMode\("edit"\); setEditSheetOpen\(true\)/);
});

test("G10 offers a non-UV procedural checker for ordinary workspace inspection", () => {
  const viewer = readFileSync(new URL("../src/ModelViewer.tsx", import.meta.url), "utf8");
  assert.match(project, /\["surface_checker", ru \? "Шахматная" : "Checker"\]/);
  assert.match(project, /viewerAppearance === "surface_checker"/);
  assert.match(project, /Процедурная сетка 10 мм · не UV/);
  assert.match(viewer, /appearance === "surface_checker"/);
  assert.match(viewer, /floor\(vModelPosition \/ 10\.0\)/);
  assert.match(viewer, /appearance === "uv_checker"/);
});
