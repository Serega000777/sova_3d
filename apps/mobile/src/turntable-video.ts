import type { Download, Job } from "@physical-ai/contracts";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export interface VerifiedTurntableVideo {
  versionId: string;
  sourceAssetId: string;
  assetId: string;
  width: 480;
  height: 320;
  fps: 12;
  frameCount: 12;
  durationSeconds: 1;
}

export interface VerifiedTurntableDownload {
  url: string;
  byteSize: number;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

/** Accept only the exact immutable-version result produced by the bounded renderer. */
export function verifiedTurntableVideoJob(
  job: Job,
  versionId: string,
): VerifiedTurntableVideo | null {
  if (
    job.type !== "render_turntable_video"
    || job.status !== "succeeded"
    || job.project_version_id !== versionId
  ) return null;
  const result = record(job.result);
  const metadata = record(result?.metadata);
  if (
    !result
    || !metadata
    || result.version_id !== versionId
    || typeof result.source_asset_id !== "string"
    || !UUID.test(result.source_asset_id)
    || typeof result.asset_id !== "string"
    || !UUID.test(result.asset_id)
    || metadata.render_kind !== "deterministic_turntable"
    || metadata.width !== 480
    || metadata.height !== 320
    || metadata.fps !== 12
    || metadata.frame_count !== 12
    || metadata.duration_seconds !== 1
  ) return null;
  return {
    versionId,
    sourceAssetId: result.source_asset_id,
    assetId: result.asset_id,
    width: 480,
    height: 320,
    fps: 12,
    frameCount: 12,
    durationSeconds: 1,
  };
}

/** Bind a fresh signed MP4 URL to the exact derived asset before native download. */
export function verifiedTurntableDownload(
  video: VerifiedTurntableVideo,
  download: Download,
): VerifiedTurntableDownload | null {
  if (
    download.asset_id !== video.assetId
    || download.format !== "mp4"
    || !Number.isSafeInteger(download.byte_size)
    || download.byte_size <= 0
    || !Number.isSafeInteger(download.expires_in_seconds)
    || download.expires_in_seconds <= 0
    || !Number.isFinite(Date.parse(download.created_at))
  ) return null;
  try {
    const url = new URL(download.url);
    if (url.protocol !== "https:") return null;
    return { url: url.toString(), byteSize: download.byte_size };
  } catch {
    return null;
  }
}
