/**
 * Scan capture (T-073, T-075, F-002).
 *
 * Plain photos through expo-camera, so this whole screen runs in Expo Go. The guidance is
 * honest about what it can measure without a depth sensor: how many frames arrived, how far
 * around the object the phone has travelled (device motion), and whether the shot was steady.
 * Depth capture (T-076/T-077) is a separate, development-build-only path; when it is
 * unavailable the screen says so instead of pretending.
 */
import { CameraView, useCameraPermissions } from "expo-camera";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { probe } from "@/src/capabilities";
import { type CaptureHint, ScanTracker } from "@/src/scan";
import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

const TARGET_FRAMES = 24;

export default function ScanScreen() {
  const router = useRouter();
  const { projectId } = useLocalSearchParams<{ projectId?: string }>();
  const { session, client } = useSession();
  const capabilities = probe();

  const camera = useRef<CameraView>(null);
  const tracker = useRef(new ScanTracker());
  const [permission, requestPermission] = useCameraPermissions();
  const [scanId, setScanId] = useState<string | null>(null);
  const [frames, setFrames] = useState(0);
  const [hint, setHint] = useState<CaptureHint>({ level: "info", message: "Point at the object." });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const stop = tracker.current.watchMotion(setHint);
    return stop;
  }, []);

  const start = useCallback(async () => {
    if (!client || !session || scanId) return;
    const scan = await client.createScan({
      workspace_id: session.workspaceId,
      project_id: projectId ?? null,
      mode: capabilities.depthScan ? "rgb_depth" : "rgb",
      capabilities: {
        runtime: capabilities.runtime,
        depth_scan: capabilities.depthScan,
        stylus: capabilities.stylus,
      },
    });
    setScanId(scan.id);
    return scan.id;
  }, [capabilities, client, projectId, scanId, session]);

  async function capture() {
    if (!client || busy) return;
    setBusy(true);
    setError(null);
    try {
      const id = scanId ?? (await start());
      if (!id) return;
      const photo = await camera.current?.takePictureAsync({ quality: 0.7, skipProcessing: true });
      if (!photo?.uri) throw new Error("the camera returned no image");
      const frame = await tracker.current.upload(client, id, photo.uri);
      setFrames(frame.sequence_no + 1);
      setHint(tracker.current.hint(frame.sequence_no + 1, TARGET_FRAMES));
      await client.updateCaptureStats(id, tracker.current.stats());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    if (!client || !scanId) return;
    setBusy(true);
    setError(null);
    try {
      await client.finalizeScan(scanId, tracker.current.scaleHint());
      router.replace(`/scan/${scanId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  if (!session) {
    return (
      <View style={[styles.screen, styles.content]}>
        <Text style={styles.muted}>Sign in to scan.</Text>
      </View>
    );
  }

  if (!permission) return <View style={styles.screen} />;
  if (!permission.granted) {
    return (
      <View style={[styles.screen, styles.content]}>
        <View style={styles.card}>
          <Text style={styles.heading}>Camera access</Text>
          <Text style={styles.muted}>
            Scanning needs the camera. Nothing is uploaded until you take a photo.
          </Text>
          <Pressable
            style={[styles.button, styles.buttonPrimary]}
            onPress={() => void requestPermission()}
          >
            <Text style={styles.buttonText}>Allow camera</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  const hintColour =
    hint.level === "warn" ? colors.yellow : hint.level === "good" ? colors.green : colors.muted;

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={{ height: 380, borderRadius: 10, overflow: "hidden" }}>
        <CameraView ref={camera} style={{ flex: 1 }} facing="back" />
      </View>

      <View style={styles.card}>
        <Text style={styles.heading}>
          {frames} / {TARGET_FRAMES} frames
        </Text>
        <Text style={[styles.text, { color: hintColour }]}>{hint.message}</Text>
        {!capabilities.depthScan && (
          <Text style={styles.muted}>{capabilities.depthScanReason}</Text>
        )}
        <View style={styles.row}>
          <Pressable
            style={[styles.button, styles.buttonPrimary, busy && { opacity: 0.5 }]}
            disabled={busy}
            onPress={capture}
          >
            <Text style={styles.buttonText}>{busy ? "Working…" : "Take frame"}</Text>
          </Pressable>
          <Pressable
            style={[styles.button, (busy || frames < 12) && { opacity: 0.5 }]}
            disabled={busy || frames < 12}
            onPress={finish}
          >
            <Text style={styles.buttonText}>Reconstruct</Text>
          </Pressable>
        </View>
        {frames > 0 && frames < 12 && (
          <Text style={styles.muted}>At least 12 frames are needed to reconstruct.</Text>
        )}
        {error && <Text style={styles.error}>{error}</Text>}
      </View>
    </ScrollView>
  );
}
