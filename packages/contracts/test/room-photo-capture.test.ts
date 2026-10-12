import assert from "node:assert/strict";
import test from "node:test";

import {
  emptyRoomPhotoSectionCounts,
  roomPhotoCoveragePercent,
  ROOM_PHOTO_SECTIONS,
  uncoveredRoomPhotoSections,
} from "../dist/room-photo-capture.js";

test("photo-room capture requires eight overlapping frames for all four walls", () => {
  const counts = emptyRoomPhotoSectionCounts();
  assert.deepEqual(uncoveredRoomPhotoSections(counts).map((item) => item.id), ["front", "right", "back", "left"]);
  for (const section of ROOM_PHOTO_SECTIONS) counts[section.id] = section.targetFrames;
  assert.equal(roomPhotoCoveragePercent(counts), 100);
  assert.deepEqual(uncoveredRoomPhotoSections(counts), []);
});

test("photo-room coverage is bounded and ignores surplus frames", () => {
  assert.equal(roomPhotoCoveragePercent({ front: 4, right: 8, back: 80, left: -2 }), 63);
});
