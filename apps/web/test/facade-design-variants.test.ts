import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { FacadeVariant, Job, Version } from "@physical-ai/contracts";

import { verifiedAppliedFacadeVariant } from "../src/lib/facade-design-variants.ts";

const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

const variant = {
  version_id: "variant-version",
  sequence_no: 4,
  name: "Warm wood",
  created_at: "2026-11-04T00:00:00Z",
  surface_keys: ["wall.front"],
  surface_assignments: [{ surface_key: "wall.front", colour: "#aa7744" }],
  category_areas_m2: {},
  assigned_area_m2: 10,
  priced_area_m2: 0,
  unpriced_assigned_area_m2: 10,
  estimated_cost: null,
  currency: null,
} as unknown as FacadeVariant;

const job = { status: "succeeded", result: { version_id: "new-version" } } as unknown as Job;
const version = {
  id: "new-version",
  parent_version_id: "source-version",
  provenance: {
    facade: {
      applied_variant: { name: "Warm wood", version_id: "variant-version" },
    },
  },
} as unknown as Version;

test("scenario 80 accepts only the exact immutable child with matching variant provenance", () => {
  assert.equal(verifiedAppliedFacadeVariant(job, version, "source-version", variant), true);
});

test("scenario 80 rejects a result bound to the wrong parent version", () => {
  assert.equal(
    verifiedAppliedFacadeVariant(
      job,
      { ...version, parent_version_id: "other-source" } as Version,
      "source-version",
      variant,
    ),
    false,
  );
});

test("scenario 80 rejects a result whose provenance names a different variant", () => {
  const wrongName = {
    ...version,
    provenance: { facade: { applied_variant: { name: "Cool stone", version_id: "variant-version" } } },
  } as Version;
  assert.equal(verifiedAppliedFacadeVariant(job, wrongName, "source-version", variant), false);

  const wrongVersionId = {
    ...version,
    provenance: { facade: { applied_variant: { name: "Warm wood", version_id: "other-variant" } } },
  } as Version;
  assert.equal(verifiedAppliedFacadeVariant(job, wrongVersionId, "source-version", variant), false);
});

test("scenario 80 rejects a job that did not succeed or whose result id does not match", () => {
  assert.equal(
    verifiedAppliedFacadeVariant(
      { ...job, status: "failed" } as Job,
      version,
      "source-version",
      variant,
    ),
    false,
  );
  assert.equal(
    verifiedAppliedFacadeVariant(
      { ...job, result: { version_id: "different-version" } } as Job,
      version,
      "source-version",
      variant,
    ),
    false,
  );
});

test("web wires applySavedFacadeVariant through the verified-provenance check", () => {
  assert.match(studio, /import \{ verifiedAppliedFacadeVariant \} from "@\/lib\/facade-design-variants";/);
  assert.match(studio, /async function applySavedFacadeVariant\(variant: FacadeVariant\)/);
  const fn = studio.slice(
    studio.indexOf("async function applySavedFacadeVariant"),
    studio.indexOf("/** Show what a job made"),
  );
  // The source version is captured before the async apply call, not re-read from
  // `activeVersion` afterward, so a later navigation cannot change what gets verified.
  assert.match(fn, /const sourceVersionId = activeVersion\.id;/);
  assert.match(fn, /client\.applyFacadeVariant\(sourceVersionId,/);
  assert.match(fn, /const version = await client\.getVersion\(versionId\);/);
  assert.match(fn, /if \(!verifiedAppliedFacadeVariant\(job, version, sourceVersionId, variant\)\) \{\s*throw new Error\(/);
});

test("web guards against a stale facade variant job hijacking the viewport after the user navigates away", () => {
  const fn = studio.slice(
    studio.indexOf("async function applySavedFacadeVariant"),
    studio.indexOf("/** Show what a job made"),
  );
  // setActiveVersion only runs when the active version is still the exact source version
  // that was captured before the job started, mirroring mobile's `activeIdRef` guard.
  assert.match(fn, /if \(activeVersionIdRef\.current === sourceVersionId\) setActiveVersion\(version\);/);
});
