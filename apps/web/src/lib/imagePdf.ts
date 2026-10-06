/** Wrap one RGB JPEG in a standards-compliant, single-page PDF without a runtime dependency. */
export function jpegToPdf(jpeg: Uint8Array, widthPx: number, heightPx: number): Uint8Array {
  if (jpeg.length < 4 || widthPx < 1 || heightPx < 1) throw new Error("invalid PDF image");
  const encoder = new TextEncoder();
  const parts: Uint8Array[] = [];
  const offsets = [0];
  let length = 0;
  const push = (part: string | Uint8Array) => {
    const bytes = typeof part === "string" ? encoder.encode(part) : part;
    parts.push(bytes);
    length += bytes.length;
  };
  const object = (number: number, body: string | Uint8Array, suffix = "") => {
    offsets[number] = length;
    push(`${number} 0 obj\n`);
    push(body);
    push(`${suffix}\nendobj\n`);
  };

  const maxPoints = 1440;
  const scale = Math.min(0.75, maxPoints / Math.max(widthPx, heightPx));
  const width = Math.max(1, Math.round(widthPx * scale));
  const height = Math.max(1, Math.round(heightPx * scale));
  const content = `q\n${width} 0 0 ${height} 0 0 cm\n/Im0 Do\nQ\n`;

  push("%PDF-1.4\n%SOVA\n");
  object(1, "<< /Type /Catalog /Pages 2 0 R >>");
  object(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>");
  object(
    3,
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${width} ${height}] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>`,
  );
  // The binary stream sits inside object 4, between its dictionary and endstream marker.
  offsets[4] = length;
  push("4 0 obj\n");
  push(`<< /Type /XObject /Subtype /Image /Width ${widthPx} /Height ${heightPx} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>\nstream\n`);
  push(jpeg);
  push("\nendstream\nendobj\n");
  object(5, `<< /Length ${encoder.encode(content).length} >>\nstream\n${content}endstream`);

  const xref = length;
  push("xref\n0 6\n0000000000 65535 f \n");
  for (let number = 1; number <= 5; number += 1) {
    push(`${String(offsets[number]).padStart(10, "0")} 00000 n \n`);
  }
  push(`trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);

  const pdf = new Uint8Array(length);
  let cursor = 0;
  for (const part of parts) {
    pdf.set(part, cursor);
    cursor += part.length;
  }
  return pdf;
}
