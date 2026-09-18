/**
 * Runtime capability probe (T-074, constitution §2a).
 *
 * Everything JS-only must run in Expo Go — that is the product owner's main manual
 * testing route. The native scan modules (ARKit/LiDAR, ARCore Depth; T-076/T-077) exist
 * only in a development build, so they are looked up at runtime and their absence is a
 * capability that is simply off, never a crash at import time.
 */
import Constants, { ExecutionEnvironment } from "expo-constants";
import { Platform } from "react-native";

export type Runtime = "expo-go" | "dev-build" | "standalone" | "web";

export interface Capabilities {
  runtime: Runtime;
  /** The JS-only baseline; always true, stated explicitly so screens can read one shape. */
  viewer3d: boolean;
  camera: boolean;
  /** Stylus pressure/tilt (Apple Pencil, S Pen) — reported by the gesture layer. */
  stylus: boolean;
  /** LiDAR / depth scanning; needs a development build with the native module. */
  depthScan: boolean;
  /** Why depthScan is off, in words a user can act on. */
  depthScanReason: string | null;
}

function runtimeOf(): Runtime {
  if (Platform.OS === "web") return "web";
  switch (Constants.executionEnvironment) {
    case ExecutionEnvironment.StoreClient:
      return "expo-go";
    case ExecutionEnvironment.Standalone:
      return "standalone";
    default:
      return "dev-build";
  }
}

/** Present only in a build that bundled the native scanner; never imported statically. */
function hasNativeScanner(): boolean {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const native = require("react-native").NativeModules as Record<string, unknown>;
    return Boolean(native.PhysicalAiScanner);
  } catch {
    return false;
  }
}

export function probe(): Capabilities {
  const runtime = runtimeOf();
  const native = runtime !== "expo-go" && runtime !== "web" && hasNativeScanner();
  return {
    runtime,
    viewer3d: true,
    camera: runtime !== "web",
    stylus: Platform.OS === "ios" || Platform.OS === "android",
    depthScan: native,
    depthScanReason: native
      ? null
      : runtime === "expo-go"
        ? "Scanning needs a development build; everything else works here in Expo Go."
        : runtime === "web"
          ? "Scanning is a phone/tablet feature."
          : "This build does not include the scanning module.",
  };
}
