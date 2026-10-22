import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  addressFacadeOpeningToFloor,
  convertToArchitecturalOpening,
  duplicateFacadeOpening,
  facadeOpeningSurfaceKeys,
  findFacadeOpeningAtPoint,
  hydrateFacadeOpenings,
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

const house = {
  length_mm: 10_000,
  width_mm: 8_000,
  floors: 3,
  floor_height_mm: 3_000,
  wall_thickness_mm: 250,
};

test("3D facade picks address all four outward-normal sides", () => {
  const openings: FacadeOpeningDraft[] = [
    { ...windowOpening, id: "front", opening_id: "front", side: "front", center_mm: 2_000 },
    { ...windowOpening, id: "back", opening_id: "back", side: "back", center_mm: 3_000 },
    { ...windowOpening, id: "left", opening_id: "left", side: "left", center_mm: 4_000 },
    { ...windowOpening, id: "right", opening_id: "right", side: "right", center_mm: 5_000 },
  ];

  assert.equal(findFacadeOpeningAtPoint(openings, { x: 2_000, y: 0, z: 1_000 }, { x: 0, y: -1, z: 0 }, house), "front");
  assert.equal(findFacadeOpeningAtPoint(openings, { x: 3_000, y: 8_000, z: 1_000 }, { x: 0, y: 1, z: 0 }, house), "back");
  assert.equal(findFacadeOpeningAtPoint(openings, { x: 0, y: 4_000, z: 1_000 }, { x: -1, y: 0, z: 0 }, house), "left");
  assert.equal(findFacadeOpeningAtPoint(openings, { x: 10_000, y: 5_000, z: 1_000 }, { x: 1, y: 0, z: 0 }, house), "right");
});

test("3D facade pick accepts jamb and head reveal normals inside the wall depth", () => {
  assert.equal(
    findFacadeOpeningAtPoint(
      [windowOpening],
      { x: 2_000, y: 125, z: 1_000 },
      { x: 1, y: 0, z: 0 },
      house,
    ),
    windowOpening.id,
  );
  assert.equal(
    findFacadeOpeningAtPoint(
      [windowOpening],
      { x: 2_000, y: 125, z: 2_100 },
      { x: 0, y: 0, z: 1 },
      house,
    ),
    windowOpening.id,
  );
});

test("3D facade pick fails closed outside the opening rectangle or facade axes", () => {
  assert.equal(
    findFacadeOpeningAtPoint([windowOpening], { x: 2_601, y: 100, z: 1_000 }, { x: 0, y: -1, z: 0 }, house),
    null,
  );
  assert.equal(
    findFacadeOpeningAtPoint([windowOpening], { x: 2_000, y: 100, z: 2_301 }, { x: 0, y: -1, z: 0 }, house),
    null,
  );
  assert.equal(
    findFacadeOpeningAtPoint([windowOpening], { x: 2_000, y: 500, z: 1_000 }, { x: 0, y: -1, z: 0 }, house),
    null,
  );
  assert.equal(
    findFacadeOpeningAtPoint([windowOpening], { x: 2_000, y: 100, z: 1_000 }, { x: 0, y: 0, z: 0 }, house),
    null,
  );
});

test("3D facade pick resolves floor-local sills from absolute model Z", () => {
  const floorOne = { ...windowOpening, id: "floor-1", opening_id: "floor-1", floor: 1 };
  const floorTwo = { ...windowOpening, id: "floor-2", opening_id: "floor-2", floor: 2 };
  assert.equal(
    findFacadeOpeningAtPoint(
      [floorOne, floorTwo],
      { x: 2_000, y: 0, z: 3_900 },
      { x: 0, y: -1, z: 0 },
      house,
    ),
    "floor-2",
  );
});

test("3D facade pick keeps legacy sill as absolute model Z", () => {
  const legacy = {
    ...windowOpening,
    id: "legacy",
    opening_id: "legacy",
    sill_mm: 3_900,
  };
  assert.equal(
    findFacadeOpeningAtPoint(
      [legacy],
      { x: 2_000, y: 0, z: 4_000 },
      { x: 0, y: -1, z: 0 },
      house,
    ),
    "legacy",
  );
});

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

test("floor addressing keeps local millimetres and fails closed outside one storey", () => {
  assert.deepEqual(
    addressFacadeOpeningToFloor(windowOpening, 2, { floors: 3, floor_height_mm: 3_000 }),
    { ...windowOpening, floor: 2 },
  );
  assert.equal(
    addressFacadeOpeningToFloor(windowOpening, 4, { floors: 3, floor_height_mm: 3_000 }),
    null,
  );
  assert.equal(
    addressFacadeOpeningToFloor(
      { ...windowOpening, sill_mm: 1_700 },
      2,
      { floors: 3, floor_height_mm: 3_000 },
    ),
    null,
  );
  assert.deepEqual(
    addressFacadeOpeningToFloor(
      { ...windowOpening, kind: "door", sill_mm: 900, height_mm: 2_100 },
      3,
      { floors: 3, floor_height_mm: 3_000 },
    ),
    { ...windowOpening, kind: "door", sill_mm: 0, height_mm: 2_100, floor: 3 },
  );
});

test("legacy opening keeps its material identity across two remount/save cycles", async () => {
  const legacyOpening = {
    kind: "window" as const,
    side: "front" as const,
    center_mm: 2_000,
    width_mm: 1_200,
    height_mm: 1_400,
    sill_mm: 900,
  };
  const assignment = {
    surface_key: "opening.legacy-aa326ce6fb0bf658.head",
    colour: "#884422",
  };

  const firstMount = await hydrateFacadeOpenings([legacyOpening]);
  const firstSurfaceKeys = firstMount.flatMap(facadeOpeningSurfaceKeys);
  const firstSavedAssignments = [assignment].filter((item) => firstSurfaceKeys.includes(item.surface_key));
  const firstSave = firstMount.map(({ id: _id, ...opening }) => opening);
  const secondMount = await hydrateFacadeOpenings(firstSave);
  const secondSurfaceKeys = secondMount.flatMap(facadeOpeningSurfaceKeys);
  const secondSavedAssignments = firstSavedAssignments.filter((item) => secondSurfaceKeys.includes(item.surface_key));
  const secondSave = secondMount.map(({ id: _id, ...opening }) => opening);

  assert.equal(firstMount[0]?.opening_id, "legacy-aa326ce6fb0bf658");
  assert.equal(secondMount[0]?.opening_id, firstMount[0]?.opening_id);
  assert.equal(secondSave[0]?.opening_id, firstSave[0]?.opening_id);
  assert.deepEqual(firstSavedAssignments, [assignment]);
  assert.deepEqual(secondSavedAssignments, [assignment]);
});

test("legacy absolute sill hydrates to an equivalent exact floor address", async () => {
  const [opening] = await hydrateFacadeOpenings(
    [{
      kind: "window",
      side: "front",
      center_mm: 2_000,
      width_mm: 1_200,
      height_mm: 1_400,
      sill_mm: 3_900,
    }],
    { floors: 3, floor_height_mm: 3_000 },
  );

  assert.equal(opening?.floor, 2);
  assert.equal(opening?.sill_mm, 900);
  assert.equal(opening?.opening_id, "legacy-0027b36e4a759a1e");
});

test("real Studio opening cards expose all three bounded actions", () => {
  const page = readFileSync(
    new URL("../src/app/projects/[id]/page.tsx", import.meta.url),
    "utf8",
  );
  assert.match(page, /duplicateFacadeOpening/);
  assert.match(page, /mirrorFacadeOpening/);
  assert.match(page, /convertToArchitecturalOpening/);
  assert.match(page, /hydrateFacadeOpenings/);
  assert.match(page, /Дублировать/);
  assert.match(page, /Зеркально/);
  assert.match(page, /В проём/);
  assert.match(page, /client\.editFacade/);
  assert.match(page, /addressFacadeOpeningToFloor/);
  assert.match(page, /findFacadeOpeningAtPoint/);
  assert.match(page, /onViewportPick/);
  assert.match(page, /selectedOpeningId/);
  assert.match(page, /scrollIntoView/);
  assert.match(page, /Этаж/);
  assert.match(page, /Абсолютная высота \(legacy\)/);
});

test("real Studio facade path offers a shed roof with its stable material surface", () => {
  const page = readFileSync(
    new URL("../src/app/projects/[id]/page.tsx", import.meta.url),
    "utf8",
  );
  assert.match(page, /<option value="shed">/);
  assert.match(page, /<option value="hip">/);
  assert.match(page, /Уклон скатов, °/);
  assert.match(page, /roof\.slope\.front/);
  assert.match(page, /Односкатная/);
  assert.match(page, /facadeRoof === "shed"/);
  assert.match(page, /"roof\.slope"/);
  assert.match(page, /client\.editFacade/);
});

test("real Studio routes roof-height commands through the facade proposal gate", () => {
  const page = readFileSync(
    new URL("../src/app/projects/[id]/page.tsx", import.meta.url),
    "utf8",
  );
  assert.match(page, /высот\(\?:а\|у\|ы\)\\s\+крыши/);
  assert.match(page, /roof\\s\+height/);
  assert.match(page, /client\.proposeFacadeCommand/);
});
