/**
 * Runtime capability probe (T-074, constitution §2a).
 *
 * Everything JS-only must run in Expo Go — that is the product owner's main manual
 * testing route. Native scan modules (ARKit/LiDAR, ARCore Depth; T-076/T-077, T-196)
 * are planned for development builds.
 *
 * `depthScan` defers entirely to `expo-room-plan`'s own `isSupported()` (Apple's
 * `RoomCaptureSession.isSupported`, itself gated by `#available(iOS 16.0, *)` on the
 * native side) — never hardcoded true, and never claimed for Expo Go, which cannot load
 * native modules at all. That native module has not yet been exercised on a physical
 * LiDAR device (T-196 acceptance); this probe reports what the platform says is possible,
 * not that this codebase has confirmed it there.
 */
import Constants, { ExecutionEnvironment } from "expo-constants";
import { isRoomPlanSupported } from "expo-room-plan";
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
  /** Voice input (F-017): the browser's speech recognition on web; a native module elsewhere. */
  voice: boolean;
  voiceReason: string | null;
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

/** The Web Speech API, when the runtime is a browser that has it. */
function hasWebSpeech(): boolean {
  const scope = globalThis as unknown as {
    SpeechRecognition?: unknown;
    webkitSpeechRecognition?: unknown;
  };
  return Boolean(scope.SpeechRecognition ?? scope.webkitSpeechRecognition);
}

/** A development build may bundle a native recogniser; Expo Go never does. */
function hasNativeSpeech(): boolean {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const native = require("react-native").NativeModules as Record<string, unknown>;
    return Boolean(native.ExpoSpeechRecognition);
  } catch {
    return false;
  }
}

export function probe(): Capabilities {
  const runtime = runtimeOf();
  const voice =
    runtime === "web"
      ? hasWebSpeech()
      : runtime !== "expo-go" && hasNativeSpeech();
  const depthScan = runtime !== "expo-go" && runtime !== "web" && isRoomPlanSupported();
  return {
    voice,
    voiceReason: voice
      ? null
      : runtime === "expo-go"
        ? "Voice input needs a development build (expo-speech-recognition); type instead."
        : runtime === "web"
          ? "This browser has no speech recognition; type instead."
          : "This build does not include speech recognition.",
    runtime,
    viewer3d: true,
    camera: runtime !== "web",
    stylus: Platform.OS === "ios" || Platform.OS === "android",
    depthScan,
    depthScanReason: depthScan
      ? null
      : runtime === "web"
        ? "LiDAR-сканирование доступно только на совместимом iPhone или iPad."
        : runtime === "expo-go"
          ? "LiDAR-сканирование требует dev-сборки (Expo Go не грузит нативные модули)."
          : "Это устройство не сообщает о поддержке RoomPlan (нужен LiDAR и iOS 16+).",
  };
}
