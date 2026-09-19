/**
 * F-019 on the phone: photograph the object (or pick a photo) and hand it to the planner
 * as an uploaded asset. expo-image-picker is part of Expo Go, so this stays in the
 * JS-only baseline (constitution §2a); the picker's own quality setting keeps a 12 MP
 * shot under the API's photo limit.
 */
import type { PhysicalAiClient } from "@physical-ai/contracts";
import * as ImagePicker from "expo-image-picker";
import { Alert, Platform } from "react-native";

import { sha256Hex } from "@/src/scan";

export interface PickedPhoto {
  uri: string;
  width: number;
  height: number;
}

/** The camera on a device, the file picker on the web; null when the user backs out. */
export async function pickPhoto(source: "camera" | "library"): Promise<PickedPhoto | null> {
  const options: ImagePicker.ImagePickerOptions = {
    mediaTypes: ["images"],
    quality: 0.6,
    exif: false,
    allowsMultipleSelection: false,
  };
  let result: ImagePicker.ImagePickerResult;
  if (source === "camera" && Platform.OS !== "web") {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      Alert.alert("Camera", "Allow the camera to photograph the object.");
      return null;
    }
    result = await ImagePicker.launchCameraAsync(options);
  } else {
    result = await ImagePicker.launchImageLibraryAsync(options);
  }
  const asset = result.canceled ? null : result.assets[0];
  return asset ? { uri: asset.uri, width: asset.width, height: asset.height } : null;
}

/** Upload the photo the client's own way (presign, PUT, complete) and return the asset id. */
export async function uploadPhoto(
  client: PhysicalAiClient,
  workspaceId: string,
  photo: PickedPhoto,
): Promise<string> {
  const response = await fetch(photo.uri);
  const blob = await response.blob();
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const contentType = blob.type === "image/png" ? "image/png" : "image/jpeg";
  const upload = await client.createUpload({
    workspace_id: workspaceId,
    filename: `photo_${Date.now()}.${contentType === "image/png" ? "png" : "jpg"}`,
    content_type: contentType,
    byte_size: bytes.byteLength,
  });
  const put = await fetch(upload.url, {
    method: "PUT",
    headers: { "Content-Type": contentType, ...upload.headers },
    body: bytes,
  });
  if (!put.ok) throw new Error(`photo upload failed (${put.status})`);
  const asset = await client.completeUpload({
    upload_id: upload.upload_id,
    sha256: await sha256Hex(bytes),
  });
  return asset.id;
}

/** How a photo-built model was sized, in words (mirrors the web). */
export function describeScale(
  scale: { source: string; confidence: string; basis?: string } | null | undefined,
): string | null {
  if (!scale) return null;
  const source =
    scale.source === "user"
      ? "your text"
      : scale.source === "reference_object"
        ? "a reference object in the photo"
        : "an estimate";
  return `Size from ${source} (${scale.confidence} confidence${scale.basis ? `: ${scale.basis}` : ""})`;
}
