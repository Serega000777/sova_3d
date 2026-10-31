import type { Download } from "@physical-ai/contracts";
import { File, Paths } from "expo-file-system";
import { isAvailableAsync, shareAsync } from "expo-sharing";

import {
  type VerifiedTurntableVideo,
  verifiedTurntableDownload,
} from "@/src/turntable-video";

interface TurntableDownloadClient {
  download(assetId: string): Promise<Download>;
}

/** Materialize the exact signed MP4 in private cache, then open native playback/sharing. */
export async function shareTurntableVideo(
  client: TurntableDownloadClient,
  video: VerifiedTurntableVideo,
): Promise<number> {
  if (!(await isAvailableAsync())) {
    throw new Error("Системное меню видео недоступно на этом устройстве.");
  }
  const download = verifiedTurntableDownload(video, await client.download(video.assetId));
  if (!download) {
    throw new Error("Сервер не вернул согласованный MP4-файл.");
  }
  const target = new File(Paths.cache, `sova-turntable-${video.assetId}.mp4`);
  const file = await File.downloadFileAsync(download.url, target, { idempotent: true });
  if (file.size !== download.byteSize) {
    file.delete();
    throw new Error("Размер загруженного MP4 не совпадает с серверным артефактом.");
  }
  await shareAsync(file.uri, {
    mimeType: "video/mp4",
    UTI: "public.mpeg-4",
    dialogTitle: "Видео обзора Sova 3D",
  });
  return download.byteSize;
}
