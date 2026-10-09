/** Fail-closed validation for a server-resolved scene transform before a renderer uses it. */
export function sceneTransformValues(value: unknown): number[] {
  if (!Array.isArray(value) || value.length !== 4) {
    throw new Error("invalid scene transform");
  }
  const rows = value.map((row) => {
    if (
      !Array.isArray(row) ||
      row.length !== 4 ||
      row.some(
        (item) => typeof item !== "number" || !Number.isFinite(item) || Math.abs(item) > 1_000_000,
      )
    ) {
      throw new Error("invalid scene transform");
    }
    return row;
  });
  const [a, b, c] = rows[0]!;
  const [d, e, f] = rows[1]!;
  const [g, h, i] = rows[2]!;
  const determinant =
    a! * (e! * i! - f! * h!) -
    b! * (d! * i! - f! * g!) +
    c! * (d! * h! - e! * g!);
  const affine = rows[3]!.every(
    (item, index) => Math.abs(item - ([0, 0, 0, 1][index] as number)) <= 1e-9,
  );
  if (!affine || Math.abs(determinant) < 1e-12) {
    throw new Error("invalid scene transform");
  }
  return rows.flat();
}
