import assert from "node:assert/strict";
import test from "node:test";

import {
  HOUSE_PDF_MIME,
  HOUSE_XLSX_MIME,
  verifiedMarketplaceDocument,
} from "../src/lib/marketplace-document.ts";

test("M06 saves only non-empty house documents with their exact MIME", () => {
  const pdf = new Blob(["%PDF-1.7"], { type: HOUSE_PDF_MIME });
  const xlsx = new Blob(["PK"], { type: HOUSE_XLSX_MIME });
  assert.equal(verifiedMarketplaceDocument(pdf, HOUSE_PDF_MIME), pdf);
  assert.equal(verifiedMarketplaceDocument(xlsx, HOUSE_XLSX_MIME), xlsx);
  assert.equal(verifiedMarketplaceDocument(new Blob([], { type: HOUSE_PDF_MIME }), HOUSE_PDF_MIME), null);
  assert.equal(verifiedMarketplaceDocument(new Blob(["{}"], { type: "application/json" }), HOUSE_PDF_MIME), null);
  assert.equal(verifiedMarketplaceDocument(pdf, HOUSE_XLSX_MIME), null);
});
