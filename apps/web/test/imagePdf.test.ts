import assert from "node:assert/strict";
import { test } from "node:test";

import { jpegToPdf } from "../src/lib/imagePdf.ts";

test("a JPEG becomes a single-page PDF with a valid xref", () => {
  const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xd9]);
  const pdf = jpegToPdf(jpeg, 800, 600);
  const text = new TextDecoder("latin1").decode(pdf);
  assert.ok(text.startsWith("%PDF-1.4"));
  assert.ok(text.includes("/Subtype /Image"));
  assert.ok(text.includes("/Width 800 /Height 600"));
  assert.ok(text.endsWith("%%EOF\n"));
  assert.deepEqual([...pdf.slice(text.indexOf("stream\n") + 7, text.indexOf("stream\n") + 11)], [
    0xff,
    0xd8,
    0xff,
    0xd9,
  ]);
});

test("invalid image dimensions are refused", () => {
  assert.throws(() => jpegToPdf(new Uint8Array([1, 2, 3, 4]), 0, 10));
});
