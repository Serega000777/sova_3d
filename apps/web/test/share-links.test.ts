import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

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
