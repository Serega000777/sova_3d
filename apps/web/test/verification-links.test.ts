import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const projectPage = readFileSync(
  new URL("../src/app/projects/[id]/page.tsx", import.meta.url),
  "utf8",
);
const verifyPage = readFileSync(
  new URL("../src/app/verify/[token]/page.tsx", import.meta.url),
  "utf8",
);

test("references 90/97: the project studio can create, list and revoke a verification link", () => {
  assert.match(projectPage, /client\.createVerificationLink\(activeVersion\.id, \{/);
  assert.match(projectPage, /\.listVerificationLinks\(activeVersion\.id\)/);
  assert.match(projectPage, /client\.revokeVerificationLink\(activeVersion\.id, linkId\)/);
  assert.match(projectPage, /expires_in_hours: verifyExpiresHours/);
  assert.match(projectPage, /window\.location\.origin\}\/verify\/\$\{created\.token\}/);
});

test("references 90/97: the public verification page needs no bearer token", () => {
  assert.match(verifyPage, /new PhysicalAiClient\(\{ baseUrl: DEFAULT_BASE_URL \}\)/);
  assert.match(verifyPage, /\.openIntegrityVerification\(token\)/);
  assert.doesNotMatch(verifyPage, /Authorization/);
  assert.match(verifyPage, /verified\.job_id/);
  assert.match(verifyPage, /не является криптографической подписью/);
  assert.match(verifyPage, /verified\.link_expires_at/);
});
