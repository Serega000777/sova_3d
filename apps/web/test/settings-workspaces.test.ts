import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/app/settings/page.tsx", import.meta.url), "utf8");

test("settings can select only a server-returned workspace", () => {
  assert.match(source, /me\?\.workspaces\.map\(\(workspace\) =>/);
  assert.match(source, /onClick=\{\(\) => selectWorkspace\(workspace\.id\)\}/);
  assert.match(source, /workspace\.id !== session\.workspaceId/);
});

test("workspace selection persists the exact id before returning to the library", () => {
  assert.match(source, /if \(!session \|\| workspaceId === session\.workspaceId\) return/);
  assert.match(source, /signIn\(\{ \.\.\.session, workspaceId \}\)/);
  assert.match(source, /router\.replace\("\/"\)/);
  assert.match(source, /aria-label=\{`\$\{t\.switchWorkspace\}: \$\{workspace\.name\}`\}/);
});
