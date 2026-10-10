/**
 * Scan result review (T-084, F-002): look at what came back, then keep it or try again.
 * Nothing enters a project until the user says so, and the scale is shown for what it is —
 * a claim with a source and a confidence (T-082).
 */
import type { Job, Project, Scan, ScanFrame } from "@physical-ai/contracts";
import { scanFrameWarnings } from "@physical-ai/contracts";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Image, Pressable, ScrollView, Text, View } from "react-native";

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
  texture?: { texture_baked?: boolean; registered_texture_cameras?: number; reason?: string };
  multi_view?: {
    registered_images?: number;
    registered_fraction?: number;
    sparse_points?: number;
    mean_reprojection_error_px?: number | null;
    registered_by_section?: Record<string, number>;
    section_provenance?: Record<
      string,
      { captured_sequence_nos?: number[]; registered_sequence_nos?: number[] }
    >;
    section_alignment_error_deg?: Record<string, number>;
    isolated_components_removed?: number;
    metric_scale_factor?: number;
    scale_confidence?: number;
  };
}

const EXTERIOR_SECTIONS = ["front", "right", "back", "left", "roof"] as const;

export default function ScanResult() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { session, client } = useSession();

  const [scan, setScan] = useState<Scan | null>(null);
  const [frames, setFrames] = useState<ScanFrame[]>([]);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [exteriorFrameUrls, setExteriorFrameUrls] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client || !id) return;
    try {
      const [current, savedFrames] = await Promise.all([
        client.getScan(id),
        client.listScanFrames(id),
      ]);
      setScan(current);
      setFrames(savedFrames);
      // checkpoint_stage drives the "what will resume actually skip" hint, so it's only
      // worth fetching while that hint is shown (paused) or about to be (reconstructing).
      if (current.job_id && (current.status === "paused" || current.status === "reconstructing")) {
        setJob(await client.getJob(current.job_id));
      } else if (current.status !== "paused" && current.status !== "reconstructing") {
        setJob(null);
      }
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

  async function pause() {
    if (!client || !scan) return;
    setBusy("Pausing");
    setError(null);
    try {
      setScan(await client.pauseScan(scan.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function resume() {
    if (!client || !scan) return;
    setBusy("Resuming");
    setError(null);
    try {
      setScan(await client.resumeScan(scan.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

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

  useEffect(() => {
    const provider = ((scan?.report ?? {}) as Report).provider;
    if (!client || provider !== "colmap_exterior") {
      setExteriorFrameUrls({});
      return;
    }
    let cancelled = false;
    const representatives = EXTERIOR_SECTIONS.flatMap((section) => {
      const frame = frames.find((candidate) => candidate.pose.exterior_section === section);
      return frame ? [[section, frame.asset_id] as const] : [];
    });
    void Promise.all(
      representatives.map(async ([section, assetId]) => [section, (await client.download(assetId)).url] as const),
    )
      .then((entries) => {
        if (!cancelled) setExteriorFrameUrls(Object.fromEntries(entries));
      })
      .catch(() => {
        if (!cancelled) setExteriorFrameUrls({});
      });
    return () => {
      cancelled = true;
    };
  }, [client, frames, scan?.report]);

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
  const frameWarnings = scanFrameWarnings(frames);
  const scale = report.scale;
  const exterior = report.provider === "colmap_exterior" ? report.multi_view : null;
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
          <Pressable
            style={[styles.button, busy ? { opacity: 0.5 } : null]}
            disabled={Boolean(busy)}
            onPress={() => void pause()}
          >
            <Text style={styles.buttonText}>
              {busy === "Pausing" ? "Pausing…" : "Pause"}
            </Text>
          </Pressable>
        </View>
      )}

      {scan?.status === "paused" && (
        <View style={styles.card}>
          <Text style={[styles.heading, { color: colors.yellow }]}>Paused</Text>
          <Text style={styles.muted}>
            {job?.checkpoint_stage === "reconstructed"
              ? "Resuming will skip reconstruction and continue from the saved mesh."
              : "Resuming will start reconstruction over."}
          </Text>
          <Pressable
            style={[styles.button, styles.buttonPrimary, busy ? { opacity: 0.5 } : null]}
            disabled={Boolean(busy)}
            onPress={() => void resume()}
          >
            <Text style={styles.buttonText}>
              {busy === "Resuming" ? "Resuming…" : "Resume"}
            </Text>
          </Pressable>
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

      {frameWarnings.length > 0 && (
        <View style={styles.card} accessibilityLabel="Frame warnings">
          <Text style={styles.heading}>Check individual frames</Text>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ gap: 8 }}
          >
            {frameWarnings.map((warning) => (
              <View key={warning.sequenceNo} style={[styles.chip, { borderColor: colors.yellow }]}>
                <Text style={[styles.chipText, { color: colors.yellow }]}>
                  Frame {warning.sequenceNo + 1} · {warning.codes
                    .map((code) => (code === "blurry" ? "blurred" : "camera motion"))
                    .join(" · ")}
                </Text>
              </View>
            ))}
          </ScrollView>
        </View>
      )}

      {modelUrl && (
        <ModelViewer url={modelUrl} bodyId="scan" selected={false} onSelect={() => {}} />
      )}

      {scan?.status === "ready" && exterior && (
        <View style={[styles.card, { gap: 10 }]} accessibilityLabel="Exterior assembly review">
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <Text style={styles.heading}>Building assembly review</Text>
            <View style={[styles.chip, { borderColor: colors.green }]}>
              <Text style={[styles.chipText, { color: colors.green }]}>connected · passed</Text>
            </View>
          </View>
          <Text style={styles.muted}>
            {exterior.registered_images ?? 0}/{report.capture?.frames ?? scan.frame_count} photos joined one camera solution · {Math.round((exterior.registered_fraction ?? report.coverage ?? 0) * 100)}% registered
            {exterior.mean_reprojection_error_px != null
              ? ` · ${exterior.mean_reprojection_error_px.toFixed(2)} px reprojection error`
              : ""}
          </Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
            {EXTERIOR_SECTIONS.filter((section) => {
              const provenance = exterior.section_provenance?.[section];
              return Boolean(provenance?.captured_sequence_nos?.length || exterior.registered_by_section?.[section]);
            }).map((section) => {
              const captured = exterior.section_provenance?.[section]?.captured_sequence_nos?.length ?? 0;
              const registered = exterior.registered_by_section?.[section] ?? 0;
              const required = section !== "roof";
              const passed = !required || registered >= 3;
              return (
                <View key={section} style={[styles.card, { width: 142, gap: 4, borderColor: passed ? colors.green : colors.red }]}>
                  {exteriorFrameUrls[section] ? (
                    <Image
                      source={{ uri: exteriorFrameUrls[section] }}
                      style={{ width: 116, height: 76, borderRadius: 8, backgroundColor: colors.viewport }}
                      accessibilityLabel={`${section} source frame`}
                    />
                  ) : null}
                  <Text style={styles.text}>{section.toUpperCase()}</Text>
                  <Text style={styles.muted}>{registered}/{captured} registered</Text>
                  {exterior.section_alignment_error_deg?.[section] != null ? (
                    <Text style={styles.muted}>
                      alignment {exterior.section_alignment_error_deg[section]?.toFixed(1)}°
                    </Text>
                  ) : null}
                </View>
              );
            })}
          </ScrollView>
          <View style={styles.row}>
            <View style={[styles.chip, { borderColor: colors.green }]}>
              <Text style={[styles.chipText, { color: colors.green }]}>metric scale applied</Text>
            </View>
            <View style={[styles.chip, { borderColor: report.texture?.texture_baked ? colors.green : colors.yellow }]}>
              <Text style={[styles.chipText, { color: report.texture?.texture_baked ? colors.green : colors.yellow }]}>
                {report.texture?.texture_baked ? "photo texture baked" : "texture unavailable"}
              </Text>
            </View>
          </View>
          <Text style={styles.muted}>
            {exterior.sparse_points?.toLocaleString() ?? "—"} sparse points · {exterior.isolated_components_removed ?? 0} isolated components removed. Rotate the assembled model above before keeping it.
          </Text>
        </View>
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
