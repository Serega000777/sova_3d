import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const overlay = readFileSync(new URL("../src/SiteCameraOverlay.tsx", import.meta.url), "utf8");
const viewer = readFileSync(new URL("../src/ModelViewer.tsx", import.meta.url), "utf8");

test("camera overlay is offered only for a server-proven site-plan version", () => {
  assert.match(project, /const hasSitePlan = Boolean\([\s\S]*?provenance[\s\S]*?site_plan/);
  assert.match(
    project,
    /\{hasSitePlan && Boolean\(modelUrl \|\| \(hasExplicitScene && sceneParts\?\.length\)\)/,
  );
  assert.match(project, /Посмотреть через камеру/);
});

test("site preview composes the live rear camera with a transparent scene viewer", () => {
  assert.match(overlay, /useCameraPermissions/);
  assert.match(overlay, /<CameraView[\s\S]*?facing="back"/);
  assert.match(
    overlay,
    /<ModelViewer[\s\S]*?transparentBackground[\s\S]*?showGrid=\{false\}/,
  );
  assert.match(viewer, /alpha: transparentBackground/);
  assert.match(viewer, /scene\.background = transparentBackground \? null/);
  assert.match(
    viewer,
    /setClearColor\([\s\S]*?transparentBackground \? 0x000000 : background,[\s\S]*?transparentBackground \? 0 : 1/,
  );
  assert.match(viewer, /makeRenderer\(gl, transparentBackground, palette\.background\)/);
});

test("manual alignment is bounded and never presented as measured AR", () => {
  assert.match(overlay, /setScale/);
  assert.match(overlay, /setRotation/);
  assert.match(overlay, /setOffsetY/);
  assert.match(overlay, /не измеренный AR\/world anchor/);
  assert.match(overlay, /нет world tracking, occlusion и координатной\s+привязки/);
  assert.doesNotMatch(overlay, /ARKit|ARCore/);
});
