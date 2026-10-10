/**
 * Object-capture coverage, shared by mobile and its tests.
 *
 * Without a depth sensor or live SfM, the only real per-frame signal is a single
 * gyro-integrated azimuth (see apps/mobile/src/scan.ts ScanTracker) — one axis around the
 * object, not a position or elevation. This deliberately reports a one-ring sector map
 * (how much of the walk-around has been covered), never a sphere/pose map the data cannot
 * back.
 */
export interface SectorCoverage {
  sectorCount: number;
  /** Index i covers [i * 360/sectorCount, (i+1) * 360/sectorCount) degrees. */
  covered: boolean[];
  coveredSectors: number;
  coveragePercent: number;
}

const DEFAULT_SECTOR_COUNT = 12;

export function azimuthSectorCoverage(
  azimuthsDeg: readonly number[],
  sectorCount: number = DEFAULT_SECTOR_COUNT,
): SectorCoverage {
  const count = Math.max(1, Math.floor(sectorCount));
  const covered = new Array<boolean>(count).fill(false);
  for (const raw of azimuthsDeg) {
    if (!Number.isFinite(raw)) continue;
    const normalized = ((raw % 360) + 360) % 360;
    const sector = Math.min(count - 1, Math.floor((normalized / 360) * count));
    covered[sector] = true;
  }
  const coveredSectors = covered.filter(Boolean).length;
  return {
    sectorCount: count,
    covered,
    coveredSectors,
    coveragePercent: Math.round((coveredSectors / count) * 100),
  };
}
