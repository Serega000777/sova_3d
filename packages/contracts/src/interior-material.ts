export type MaterialTriangle = readonly [
  readonly [number, number, number],
  readonly [number, number, number],
  readonly [number, number, number],
];

/** Dominant-axis box projection in object-local platform millimetres. Ties are X, then Y, then Z. */
export function projectMaterialTriangleUv(
  triangle: MaterialTriangle,
  tileSizeMm: number,
): [[number, number], [number, number], [number, number]] {
  if (!Number.isFinite(tileSizeMm) || tileSizeMm <= 0) throw new Error("invalid texture tile size");
  const [a, b, c] = triangle;
  const ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const ac = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
  const normal = [
    ab[1]! * ac[2]! - ab[2]! * ac[1]!,
    ab[2]! * ac[0]! - ab[0]! * ac[2]!,
    ab[0]! * ac[1]! - ab[1]! * ac[0]!,
  ];
  const absolute = normal.map(Math.abs);
  const axis = absolute[0]! >= absolute[1]! && absolute[0]! >= absolute[2]!
    ? 0
    : absolute[1]! >= absolute[2]! ? 1 : 2;
  return triangle.map((point) => [
    (axis === 0 ? point[1] : point[0]) / tileSizeMm,
    (axis === 2 ? point[1] : point[2]) / tileSizeMm,
  ]) as [[number, number], [number, number], [number, number]];
}
