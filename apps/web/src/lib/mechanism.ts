/** Row-major platform-mm transform for the bounded hinged-lid kinematic preview. */
export function hingedLidTransform(angleDeg: number, pivotZMm: number): number[][] {
  const safeAngle = Number.isFinite(angleDeg) ? Math.max(0, Math.min(180, angleDeg)) : 0;
  const safePivot = Number.isFinite(pivotZMm) ? pivotZMm : 0;
  const angle = safeAngle * Math.PI / 180;
  const rawCosine = Math.cos(angle);
  const rawSine = Math.sin(angle);
  const cosine = Math.abs(rawCosine) < 1e-12 ? 0 : rawCosine;
  const sine = Math.abs(rawSine) < 1e-12 ? 0 : rawSine;
  const negativeSine = sine === 0 ? 0 : -sine;
  return [
    [1, 0, 0, 0],
    [0, cosine, negativeSine, 0],
    [0, sine, cosine, safePivot],
    [0, 0, 0, 1],
  ];
}
