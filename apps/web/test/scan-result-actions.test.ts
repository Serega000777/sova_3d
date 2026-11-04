import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const scan = readFileSync(new URL("../src/app/scanner/[id]/page.tsx", import.meta.url), "utf8");
const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");

test("competitor scan-result rail exposes only real result surfaces", () => {
  assert.match(scan, /className="scan-result-actions"/);
  assert.match(scan, /setShowEmptyRoom\(false\)/);
  assert.match(scan, /roomShellUrl && \(/);
  assert.match(scan, /href="#scan-room-measurements"/);
  assert.match(scan, /scan\.status === "accepted" && scan\.project_id && measuredPlan/);
  assert.match(scan, /\/plan\?project_id=\$\{encodeURIComponent\(scan\.project_id\)\}/);
  assert.match(scan, /\/projects\/\$\{scan\.project_id\}\?tool=repair/);
  assert.match(scan, /\/projects\/\$\{scan\.project_id\}\?tool=export/);
});

test("deep links open the exact existing Studio tools", () => {
  assert.match(studio, /requested === "repair"/);
  assert.match(studio, /requested === "export"/);
});

test("result actions have responsive original Sova styling", () => {
  assert.match(css, /\.scan-result-actions/);
  assert.match(css, /@media \(min-width: 981px\)/);
  assert.match(css, /border-color: var\(--accent\)/);
});
