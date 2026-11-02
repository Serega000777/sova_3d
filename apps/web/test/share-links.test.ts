import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { sharedViewerFormat } from "../src/lib/share-links.ts";

const projectPage = readFileSync(
  new URL("../src/app/projects/[id]/page.tsx", import.meta.url),
  "utf8",
);
const sharedPage = readFileSync(
  new URL("../src/app/shared/[token]/page.tsx", import.meta.url),
  "utf8",
);

test("reference 62/64: the project studio can create, list and revoke a share link", () => {
  assert.match(projectPage, /client\.createProjectShareLink\(project\.id, \{/);
  assert.match(projectPage, /client\.listProjectShareLinks\(project\.id\)/);
  assert.match(projectPage, /client\.revokeProjectShareLink\(project\.id, linkId\)/);
  assert.match(projectPage, /expires_in_hours: shareExpiresHours/);
  assert.match(projectPage, /window\.location\.origin\}\/shared\/\$\{created\.token\}/);
  assert.match(projectPage, /повторно показать её нельзя/);
});

test("reference 62/64: the public share page needs no bearer token to open a link", () => {
  assert.match(sharedPage, /new PhysicalAiClient\(\{ baseUrl: DEFAULT_BASE_URL \}\)/);
  assert.match(sharedPage, /\.openSharedProject\(token\)/);
  assert.doesNotMatch(sharedPage, /token: .*session\.token|Authorization/);
  assert.match(sharedPage, /shared\.model\.download_url/);
  assert.match(sharedPage, /shared\.link_expires_at/);
});

test("reference 62: the public page embeds only formats supported by the read-only viewer", () => {
  assert.equal(sharedViewerFormat("stl"), "stl");
  assert.equal(sharedViewerFormat("GLB"), "glb");
  assert.equal(sharedViewerFormat("gltf"), "glb");
  assert.equal(sharedViewerFormat("obj"), null);
  assert.equal(sharedViewerFormat("3mf"), null);
  assert.match(sharedPage, /dynamic\(/);
  assert.match(sharedPage, /<ModelViewer/);
  assert.match(sharedPage, /format=\{viewerFormat\}/);
  assert.match(sharedPage, /onSelect=\{\(\) => undefined\}/);
  assert.match(sharedPage, /Просмотр не создаёт сессию/);
});
