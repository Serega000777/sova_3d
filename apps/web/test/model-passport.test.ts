import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const passport = readFileSync(new URL("../src/components/ModelPassportCard.tsx", import.meta.url), "utf8");
const integrity = readFileSync(new URL("../src/components/IntegrityCheckPanel.tsx", import.meta.url), "utf8");
const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");
const verification = readFileSync(new URL("../src/components/VerificationLinksCard.tsx", import.meta.url), "utf8");

test("reference 97 passport shows canonical version identity and measured facts", () => {
  assert.match(passport, /projectId: project\.id/);
  assert.match(passport, /versionId: version\.id/);
  assert.match(passport, /sequenceNo: version\.sequence_no/);
  assert.match(passport, /history\?\.creator_name/);
  assert.match(passport, /createdAt: version\.created_at/);
  assert.match(passport, /storedFileCount: version\.assets\.length/);
  assert.match(passport, /report\?\.output\.bboxSizeMm/);
  assert.match(passport, /data-testid="passport-not-checked"/);
});

test("reference 97 text copy includes both stable IDs and the version sequence", () => {
  assert.match(passport, /navigator\.clipboard\.writeText\(modelPassportText\(data, language\)\)/);
  assert.match(passport, /Project ID.*data\.projectId/s);
  assert.match(passport, /Version.*data\.sequenceNo.*data\.versionId/s);
  assert.match(passport, /Integrity check.*status/s);
  assert.match(passport, /Dimensions.*dimensionsText/s);
});

test("passport reuses the exact report and PDF state and clears it before a version reload", () => {
  assert.match(integrity, /const visibleReport = reportVersionId === versionId \? report : null/);
  assert.match(integrity, /setReportVersionId\(versionId\);\s*setReport\(null\)/);
  assert.match(integrity, /report=\{visibleReport\}/);
  assert.match(integrity, /onDownloadPdf=\{\(\) => void downloadPdf\(\)\}/);
  assert.match(integrity, /visibleReport && verificationLinksCard/);
  assert.match(studio, /setCreatedVerificationLink\(null\);\s*setVerificationLinks\(\[\]\);/);
  assert.match(studio, /verificationLinkRevision\.current === request/);
});

test("only the project owner receives the version-bound verification-link card", () => {
  assert.match(studio, /verificationLinksCard=\{isProjectOwner \? \(/);
  assert.match(studio, /<VerificationLinksCard/);
  assert.match(verification, /data-testid="passport-verification-links"/);
  assert.match(verification, /no cryptographic signature/);
});
