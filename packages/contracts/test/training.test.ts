/** Self-learning plan steps 1-2: the consent and feedback copy every client renders. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { FEEDBACK_RATINGS, FEEDBACK_REASONS, TRAINING_CONSENT_COPY } from "../src/training.ts";

test("every feedback rating has a bilingual label and matches the API's enum", () => {
  assert.deepEqual(
    new Set(FEEDBACK_RATINGS.map((r) => r.id)),
    new Set(["good", "bad", "fixed"]),
  );
  for (const rating of FEEDBACK_RATINGS) {
    assert.ok(rating.label.ru.length > 0, rating.id);
    assert.ok(rating.label.en.length > 0, rating.id);
  }
});

test("every bad-rating reason has a bilingual label and matches the API's enum", () => {
  assert.deepEqual(
    new Set(FEEDBACK_REASONS.map((r) => r.id)),
    new Set(["prompt_mismatch", "broken_geometry", "low_detail_quality", "other"]),
  );
  for (const reason of FEEDBACK_REASONS) {
    assert.ok(reason.label.ru.length > 0, reason.id);
    assert.ok(reason.label.en.length > 0, reason.id);
  }
});

test("the consent copy is filled in for both languages", () => {
  for (const entry of Object.values(TRAINING_CONSENT_COPY)) {
    assert.ok(entry.ru.length > 0);
    assert.ok(entry.en.length > 0);
  }
});
