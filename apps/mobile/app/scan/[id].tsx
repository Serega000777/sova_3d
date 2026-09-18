/**
 * Scan result review (T-084, F-002): look at what came back, then keep it or try again.
 * Nothing enters a project until the user says so, and the scale is shown for what it is —
 * a claim with a source and a confidence (T-082).
 */
import type { Project, Scan } from "@physical-ai/contracts";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { ModelViewer } from "@/src/ModelViewer";
import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

interface Report {
  provider?: string;
  coverage?: number;
  note?: string;
  placeholder?: boolean;
  scale?: { applied_mm: number; source: string; confidence: number; warning: string | null };
  capture?: { frames?: number; blurry_frames?: number; mean_sharpness?: number | null };
  repair?: Record<string, unknown>;
}

export default function ScanResult() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { session, client } = useSession();

  const [scan, setScan] = useState<Scan | null>(null);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client || !id) return;
    try {
      setScan(await client.getScan(id));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [client, id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Reconstruction runs in the background; poll while it does.
  useEffect(() => {
    if (!scan || scan.status !== "reconstructing") return;
    const timer = setInterval(() => void refresh(), 3000);
    return () => clearInterval(timer);
  }, [refresh, scan]);

  useEffect(() => {
    if (!client || !scan?.mesh_asset_id) {
      setModelUrl(null);
      return;
    }
    let cancelled = false;
    void client.download(scan.mesh_asset_id).then((d) => !cancelled && setModelUrl(d.url));
    return () => {
      cancelled = true;
    };
  }, [client, scan?.mesh_asset_id]);

  useEffect(() => {
    if (!client || !session || scan?.project_id) return;
    void client.listProjects(session.workspaceId).then(setProjects).catch(() => undefined);
  }, [client, session, scan?.project_id]);

  async function keep(projectId?: string) {
    if (!client || !scan) return;
    setBusy("Saving");
    setError(null);
    try {
      const saved = await client.acceptScan(scan.id, { project_id: projectId ?? null });
      setScan(saved);
      if (saved.project_id) router.replace(`/project/${saved.project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function retry() {
    if (!client || !scan) return;
    setBusy("Discarding");
    try {
      await client.cancelScan(scan.id);
      router.replace("/scan");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(null);
    }
  }

  const report = (scan?.report ?? {}) as Report;
  const scale = report.scale;
  const confidenceColour =
    !scale || scale.confidence < 0.3
      ? colors.red
      : scale.confidence < 0.7
        ? colors.yellow
        : colors.green;

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: scan?.label ?? "Scan" }} />

      {scan?.status === "reconstructing" && (
        <View style={styles.card}>
          <Text style={styles.heading}>Reconstructing…</Text>
          <Text style={styles.muted}>
            {scan.frame_count} frames are being turned into a model. This keeps running if you
            leave the screen.
          </Text>
        </View>
      )}

      {scan?.status === "failed" && (
        <View style={styles.card}>
          <Text style={styles.heading}>The scan did not reconstruct</Text>
          <Text style={styles.error}>
            {(scan.error as { message?: string } | null)?.message ?? "unknown error"}
          </Text>
          <Pressable style={[styles.button, styles.buttonPrimary]} onPress={retry}>
            <Text style={styles.buttonText}>Scan again</Text>
          </Pressable>
        </View>
      )}

      {modelUrl && (
        <ModelViewer url={modelUrl} bodyId="scan" selected={false} onSelect={() => {}} />
      )}

      {scale && (
        <View style={styles.card}>
          <Text style={styles.heading}>Size</Text>
          <Text style={styles.text}>
            {scale.applied_mm.toFixed(1)} mm across ·{" "}
            <Text style={{ color: confidenceColour }}>
              {scale.source === "depth"
                ? "measured by the depth sensor"
                : scale.source === "scale_hint"
                  ? "from the size you gave"
                  : "assumed"}
            </Text>
          </Text>
          {scale.warning && <Text style={[styles.muted, { color: colors.yellow }]}>{scale.warning}</Text>}
        </View>
      )}

      {scan?.status === "ready" && (
        <View style={styles.card}>
          <Text style={styles.heading}>Capture</Text>
          <Text style={styles.muted}>
            {report.capture?.frames ?? scan.frame_count} frames ·{" "}
            {Math.round((report.coverage ?? 0) * 100)}% coverage
            {report.capture?.blurry_frames ? ` · ${report.capture.blurry_frames} blurry` : ""}
          </Text>
          {report.placeholder && <Text style={styles.muted}>{report.note}</Text>}
        </View>
      )}

      {scan?.status === "ready" && (
        <View style={styles.card}>
          <Text style={styles.heading}>Keep this scan?</Text>
          {scan.project_id ? (
            <Pressable
              style={[styles.button, styles.buttonPrimary, busy ? { opacity: 0.5 } : null]}
              disabled={Boolean(busy)}
              onPress={() => keep()}
            >
              <Text style={styles.buttonText}>Save to the project</Text>
            </Pressable>
          ) : (
            projects.map((project) => (
              <Pressable
                key={project.id}
                style={[styles.button, busy ? { opacity: 0.5 } : null]}
                disabled={Boolean(busy)}
                onPress={() => keep(project.id)}
              >
                <Text style={styles.buttonText}>Save to “{project.name}”</Text>
              </Pressable>
            ))
          )}
          <Pressable style={styles.button} disabled={Boolean(busy)} onPress={retry}>
            <Text style={styles.buttonText}>Discard and scan again</Text>
          </Pressable>
        </View>
      )}

      {error && <Text style={styles.error}>{error}</Text>}
    </ScrollView>
  );
}
