/**
 * Guided capture (T-075) and resumable frame upload (T-078), JS only so it runs in Expo Go.
 *
 * Without a depth sensor there is no true coverage measure, so the tracker reports what it
 * can actually observe: how many frames arrived, how far the phone has turned around the
 * object (device motion integrated over time), and how steady the phone was when the
 * shutter fired. Those measurements ride along with each frame and end up in the
 * reconstruction report, where the scale is stated as a claim rather than a fact.
 */
import type { PhysicalAiClient, ScanFrame } from "@physical-ai/contracts";

export interface CaptureHint {
  level: "info" | "good" | "warn";
  message: string;
}

interface Measured {
  sharpness: number;
  azimuth_deg: number;
  steady: boolean;
}

const SHAKE_LIMIT = 1.2; // rad/s; above this the shot is likely blurred

export class ScanTracker {
  private next = 0;
  private azimuth = 0;
  private rotationRate = 0;
  private lastSample = 0;
  private measurements: Measured[] = [];
  /** Frames whose upload failed, retried on the next capture (T-078). */
  private pending: { sequence_no: number; uri: string }[] = [];

  /**
   * Integrate the gyroscope into an azimuth estimate. expo-sensors is part of Expo Go;
   * if it is missing or silent the tracker simply reports no angle.
   */
  watchMotion(onHint: (hint: CaptureHint) => void): () => void {
    let cancelled = false;
    let remove: (() => void) | undefined;
    void (async () => {
      try {
        const { DeviceMotion } = await import("expo-sensors");
        if (cancelled || !(await DeviceMotion.isAvailableAsync())) return;
        DeviceMotion.setUpdateInterval(200);
        const subscription = DeviceMotion.addListener((event) => {
          const now = Date.now();
          const dt = this.lastSample ? (now - this.lastSample) / 1000 : 0;
          this.lastSample = now;
          const rate = event.rotationRate?.gamma ?? 0;
          this.rotationRate = Math.abs(rate);
          this.azimuth += rate * dt * (180 / Math.PI);
          if (this.rotationRate > SHAKE_LIMIT) {
            onHint({ level: "warn", message: "Slow down — the phone is moving too fast." });
          }
        });
        remove = () => subscription.remove();
      } catch {
        // No motion sensors (simulator, web): capture still works, angle is unknown.
      }
    })();
    return () => {
      cancelled = true;
      remove?.();
    };
  }

  hint(frames: number, target: number): CaptureHint {
    if (frames >= target) {
      return { level: "good", message: "Enough frames — reconstruct when ready." };
    }
    const turned = Math.abs(this.azimuth);
    if (frames >= 6 && turned < 45) {
      return { level: "warn", message: "Walk around the object — all frames are from one side." };
    }
    return {
      level: "info",
      message: `Keep going: ${target - frames} more frames, about ${Math.max(
        0,
        Math.round(360 - turned),
      )}° left to cover.`,
    };
  }

  stats(): Record<string, unknown> {
    const sharp = this.measurements.map((m) => m.sharpness);
    return {
      frames: this.measurements.length,
      azimuth_deg: Math.round(this.azimuth),
      mean_sharpness: sharp.length ? sharp.reduce((a, b) => a + b, 0) / sharp.length : null,
      shaky_frames: this.measurements.filter((m) => !m.steady).length,
      pending_uploads: this.pending.length,
    };
  }

  /** Nothing measured the object, so no size is claimed unless the user gives one. */
  scaleHint(): { scale_hint_mm?: number; scale_confidence?: number } {
    return {};
  }

  async upload(client: PhysicalAiClient, scanId: string, uri: string): Promise<ScanFrame> {
    // Retry whatever failed earlier first, so a recovered connection catches up in order.
    for (const stale of [...this.pending]) {
      try {
        await this.send(client, scanId, stale.sequence_no, stale.uri);
        this.pending = this.pending.filter((p) => p.sequence_no !== stale.sequence_no);
      } catch {
        break; // still offline; keep the queue for the next attempt
      }
    }

    const sequence_no = this.next++;
    try {
      return await this.send(client, scanId, sequence_no, uri);
    } catch (error) {
      this.pending.push({ sequence_no, uri });
      throw error;
    }
  }

  private async send(
    client: PhysicalAiClient,
    scanId: string,
    sequence_no: number,
    uri: string,
  ): Promise<ScanFrame> {
    const response = await fetch(uri);
    const blob = await response.blob();
    const bytes = new Uint8Array(await blob.arrayBuffer());
    const quality = this.measure(bytes);

    const upload = await client.createUpload({
      workspace_id: await this.workspaceOf(client, scanId),
      filename: `frame_${String(sequence_no).padStart(5, "0")}.jpg`,
      content_type: "image/jpeg",
      byte_size: bytes.byteLength,
    });
    const put = await fetch(upload.url, {
      method: "PUT",
      headers: { "Content-Type": "image/jpeg" },
      body: bytes,
    });
    if (!put.ok) throw new Error(`frame upload failed (${put.status})`);
    const asset = await client.completeUpload({
      upload_id: upload.upload_id,
      sha256: await sha256Hex(bytes),
    });

    const frame = await client.addScanFrame(scanId, {
      asset_id: asset.id,
      sequence_no,
      kind: "rgb",
      pose: { azimuth_deg: Math.round(this.azimuth) },
      quality,
    });
    this.measurements.push({
      sharpness: quality.sharpness,
      azimuth_deg: quality.azimuth_deg,
      steady: quality.steady,
    });
    return frame;
  }

  private workspaceCache = new Map<string, string>();

  private async workspaceOf(client: PhysicalAiClient, scanId: string): Promise<string> {
    const cached = this.workspaceCache.get(scanId);
    if (cached) return cached;
    const scan = await client.getScan(scanId);
    this.workspaceCache.set(scanId, scan.workspace_id);
    return scan.workspace_id;
  }

  /**
   * A cheap blur proxy: JPEG compresses a soft frame far harder than a crisp one, so
   * bytes-per-pixel tracks sharpness well enough to warn on obviously blurred shots.
   * A real focus measure needs the raw pixels, which Expo Go cannot give us.
   */
  private measure(bytes: Uint8Array): Measured & Record<string, unknown> {
    const kilobytes = bytes.byteLength / 1024;
    const sharpness = Math.max(0, Math.min(1, (kilobytes - 40) / 360));
    return {
      sharpness: Number(sharpness.toFixed(3)),
      azimuth_deg: Math.round(this.azimuth),
      steady: this.rotationRate <= SHAKE_LIMIT,
      bytes: bytes.byteLength,
      method: "jpeg_size_proxy",
    };
  }
}

/** Web Crypto is available in Expo Go (Hermes) and on web. */
export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes as unknown as ArrayBuffer);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
