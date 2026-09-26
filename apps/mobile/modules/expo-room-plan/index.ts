/**
 * T-196: native iOS RoomPlan (LiDAR) capture, as a local Expo module.
 *
 * Expo Go can never load this — it has no native code beyond what Expo ships — so every
 * export here degrades honestly instead of throwing when the native side is missing: the
 * capability probe (`src/capabilities.ts`) is what callers should check before touching
 * this module at all.
 */
import { requireNativeModule, requireNativeViewManager } from "expo-modules-core";
import type { ComponentType } from "react";

import type { RoomCaptureViewProps } from "./src/ExpoRoomPlan.types";

interface NativeExpoRoomPlan {
  isSupported(): boolean;
}

let native: NativeExpoRoomPlan | null = null;
try {
  native = requireNativeModule<NativeExpoRoomPlan>("ExpoRoomPlan");
} catch {
  native = null; // Expo Go, web, Android, or a build from before this module was added
}

/** True only on an iOS development/standalone build, with the native module linked, on a
 * device RoomPlan itself reports as capable (LiDAR present, iOS 16+). */
export function isRoomPlanSupported(): boolean {
  try {
    return native?.isSupported() ?? false;
  } catch {
    return false;
  }
}

/**
 * Hosts Apple's own `RoomCaptureView` (camera feed plus RoomPlan's live scanning
 * overlay) — this module adds no rendering of its own. Mount it only behind
 * `isRoomPlanSupported()`; on a platform without the native module the import above
 * already failed quietly, so this component would have nothing to render.
 */
export const RoomCaptureView = native
  ? (requireNativeViewManager<RoomCaptureViewProps>("ExpoRoomPlan") as ComponentType<RoomCaptureViewProps>)
  : null;

export * from "./src/ExpoRoomPlan.types";
