import assert from "node:assert/strict";
import test from "node:test";

import { GUIDED_PHOTO_VIEWS, assessGuidedPhotos } from "../src/multi-photo.ts";

test("four distinct labelled, adequately sized photos pass the guided gate", () => {
  const result = assessGuidedPhotos(
    GUIDED_PHOTO_VIEWS.map((view, index) => ({
      view,
      width: 1600,
      height: 1200,
      byteSize: 240_000,
      fingerprint: `photo-${index}`,
    })),
  );
  assert.equal(result.ready, true);
  assert.deepEqual(result.slots.map((slot) => slot.issues), [[], [], [], []]);
});

test("missing, small, extreme and duplicate views fail with exact reasons", () => {
  const result = assessGuidedPhotos([
    { view: "front", width: 640, height: 480, byteSize: 20_000, fingerprint: "same" },
    { view: "right", width: 2400, height: 600, byteSize: 200_000, fingerprint: "same" },
  ]);
  assert.equal(result.ready, false);
  assert.deepEqual(result.slots[0]?.issues, ["low_resolution", "file_too_small", "duplicate"]);
  assert.deepEqual(result.slots[1]?.issues, ["low_resolution", "extreme_aspect", "duplicate"]);
  assert.deepEqual(result.slots[2]?.issues, ["missing"]);
  assert.deepEqual(result.slots[3]?.issues, ["missing"]);
});
