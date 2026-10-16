import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  convertToArchitecturalOpening,
  duplicateFacadeOpening,
  mirrorFacadeOpening,
  type FacadeOpeningDraft,
} from "../src/lib/facade-openings.ts";

const windowOpening: FacadeOpeningDraft = {
  id: "front-window",
  opening_id: "front-window",
  kind: "window",
  side: "front",
  center_mm: 2_000,
  width_mm: 1_200,
  height_mm: 1_400,
  sill_mm: 900,
};

test("mirror uses the selected facade span and preserves semantic identity", () => {
  assert.deepEqual(
    mirrorFacadeOpening(windowOpening, { length_mm: 10_000, width_mm: 8_000 }),
    { ...windowOpening, center_mm: 8_000 },
  );
  assert.equal(
    mirrorFacadeOpening(
      { ...windowOpening, side: "left", center_mm: 1_500 },
      { length_mm: 10_000, width_mm: 8_000 },
    )?.center_mm,
    6_500,
  );
});

test("mirror fails closed for invalid draft geometry", () => {
  assert.equal(
    mirrorFacadeOpening(
      { ...windowOpening, center_mm: Number.NaN },
      { length_mm: 10_000, width_mm: 8_000 },
    ),
    null,
  );
  assert.equal(
    mirrorFacadeOpening(
      { ...windowOpening, center_mm: 9_700 },
      { length_mm: 10_000, width_mm: 8_000 },
    ),
    null,
  );
  assert.equal(
    mirrorFacadeOpening(
      { ...windowOpening, width_mm: Number.NaN },
      { length_mm: 10_000, width_mm: 8_000 },
    ),
    null,
  );
});

test("duplicate gets a new stable opening id and rejects unsafe ids", () => {
  assert.deepEqual(duplicateFacadeOpening(windowOpening, "front-window-copy"), {
    ...windowOpening,
    id: "front-window-copy",
    opening_id: "front-window-copy",
  });
  assert.equal(duplicateFacadeOpening(windowOpening, "front-window"), null);
  assert.equal(duplicateFacadeOpening(windowOpening, "Not safe"), null);
});

test("convert preserves dimensions and identity but marks an unfilled opening", () => {
  assert.deepEqual(convertToArchitecturalOpening(windowOpening), {
    ...windowOpening,
    kind: "opening",
  });
});

test("real Studio opening cards expose all three bounded actions", () => {
  const page = readFileSync(
    new URL("../src/app/projects/[id]/page.tsx", import.meta.url),
    "utf8",
  );
  assert.match(page, /duplicateFacadeOpening/);
  assert.match(page, /mirrorFacadeOpening/);
  assert.match(page, /convertToArchitecturalOpening/);
  assert.match(page, /Дублировать/);
  assert.match(page, /Зеркально/);
  assert.match(page, /В проём/);
  assert.match(page, /client\.editFacade/);
});

test("real Studio facade path offers a shed roof with its stable material surface", () => {
  const page = readFileSync(
    new URL("../src/app/projects/[id]/page.tsx", import.meta.url),
    "utf8",
  );
  assert.match(page, /<option value="shed">/);
  assert.match(page, /Односкатная/);
  assert.match(page, /facadeRoof === "shed"/);
  assert.match(page, /"roof\.slope"/);
  assert.match(page, /client\.editFacade/);
});
