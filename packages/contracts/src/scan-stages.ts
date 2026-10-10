/** Where a scan is on its way from the camera to the project, from its real status. */
export const SCAN_STAGE_COUNT = 4;

/** 0 capture, 1 processing, 2 ready, 3 in the project; null for a failed, cancelled or unknown scan. */
export function scanStage(status: string): number | null {
  switch (status) {
    case "capturing":
    case "uploading":
      return 0;
    case "reconstructing":
    case "paused":
      return 1;
    case "ready":
      return 2;
    case "accepted":
      return 3;
    default:
      return null;
  }
}
