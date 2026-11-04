import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  facadeRequestSurfaceKeys,
  facadeVariantCompatibility,
  verifiedAppliedFacadeVariant,
} from "../src/facade-design-variants.ts";

const request = {
  wall_thickness_mm: 250,
  roof: "gable",
  roof_height_mm: 1200,
  overhang_mm: 300,
  openings: [
    {
      opening_id: "front-window",
      kind: "window",
      side: "front",
      center_mm: 3000,
      width_mm: 1200,
      height_mm: 1400,
      sill_mm: 900,
    },
    {
      opening_id: "entry",
      kind: "door",
      side: "front",
      center_mm: 6000,
      width_mm: 1000,
      height_mm: 2100,
      sill_mm: 0,
    },
  ],
};

const compatibleVariant = {
  version_id: "variant-version",
  sequence_no: 4,
  name: "Warm wood",
  created_at: "2026-11-04T00:00:00Z",
  surface_keys: facadeRequestSurfaceKeys(request),
  surface_assignments: [{ surface_key: "wall.front", colour: "#aa7744" }],
  category_areas_m2: {},
  assigned_area_m2: 10,
  priced_area_m2: 0,
  unpriced_assigned_area_m2: 10,
  estimated_cost: null,
  currency: null,
};

test("exact facade variant compatibility includes roof and stable opening-frame roles", () => {
  const keys = facadeRequestSurfaceKeys(request);
  assert.ok(keys.includes("roof.slope.left"));
  assert.ok(keys.includes("opening.front-window.sill"));
  assert.ok(keys.includes("opening.entry.head"));
  assert.equal(keys.includes("opening.entry.sill"), false);
  assert.equal(facadeVariantCompatibility(request, compatibleVariant), "compatible");
  assert.equal(
    facadeVariantCompatibility(request, { ...compatibleVariant, surface_keys: ["wall.front"] }),
    "incompatible",
  );
});

test("legacy openings defer their geometry-derived identity to the server", () => {
  const legacy = { ...request, openings: [{ ...request.openings[0], opening_id: null }] };
  assert.equal(facadeRequestSurfaceKeys(legacy), null);
  assert.equal(facadeVariantCompatibility(legacy, compatibleVariant), "server_check");
});

test("applied result must be the exact immutable child with selected variant provenance", () => {
  const job = { status: "succeeded", result: { version_id: "new-version" } };
  const version = {
    id: "new-version",
    parent_version_id: "source-version",
    provenance: {
      facade: {
        applied_variant: { name: "Warm wood", version_id: "variant-version" },
      },
    },
  };
  assert.equal(
    verifiedAppliedFacadeVariant(job, version, "source-version", compatibleVariant),
    true,
  );
  assert.equal(
    verifiedAppliedFacadeVariant(job, { ...version, parent_version_id: "other" }, "source-version", compatibleVariant),
    false,
  );
  assert.equal(
    verifiedAppliedFacadeVariant(
      job,
      { ...version, provenance: { facade: { applied_variant: { name: "Other", version_id: "variant-version" } } } },
      "source-version",
      compatibleVariant,
    ),
    false,
  );
});

test("project properties exposes the server-owned facade variant card", () => {
  const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
  const card = readFileSync(new URL("../src/FacadeDesignVariantsCard.tsx", import.meta.url), "utf8");
  assert.match(project, /<FacadeDesignVariantsCard/);
  assert.match(card, /client\.listFacadeVariants\(projectId\)/);
  assert.match(card, /client\.applyFacadeVariant\(sourceVersionId/);
  assert.match(card, /client\.waitForJob\(accepted\.job_id\)/);
  assert.match(card, /verifiedAppliedFacadeVariant\(job, version, sourceVersionId, variant\)/);
});
