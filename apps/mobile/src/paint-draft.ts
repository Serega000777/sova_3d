export function removePaintStroke<T>(strokes: readonly T[], index: number): T[] {
  if (!Number.isInteger(index) || index < 0 || index >= strokes.length) return [...strokes];
  return strokes.filter((_stroke, strokeIndex) => strokeIndex !== index);
}
