import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { componentLibraryView } from "../src/component-library.ts";

const parts = [
  { id: "pi", name: "Raspberry Pi", kind: "board", screw: "M2.5", aliases: ["малина"] },
  { id: "motor", name: "N20 Motor", kind: "motor", screw: "M2", aliases: ["мотор"] },
];

test("component library combines search with honest catalogue groups", () => {
  assert.deepEqual(componentLibraryView(parts, "малина", "electronics").map((part) => part.id), ["pi"]);
  assert.deepEqual(componentLibraryView(parts, "motor", "mechanics").map((part) => part.id), ["motor"]);
  assert.deepEqual(componentLibraryView(parts, "motor", "electronics"), []);
});

test("mobile component library uses the typed catalogue and terminal enclosure job", () => {
  const source = readFileSync(new URL("../app/components.tsx", import.meta.url), "utf8");
  assert.match(source, /client\.listComponents\(undefined, "ru"\)/);
  assert.match(source, /client\.buildEnclosure/);
  assert.match(source, /await client\.waitForJob/);
  assert.match(source, /job\.status !== "succeeded"/);
  assert.match(source, /Каталог не содержит готовую 3D-модель компонента/);
});
