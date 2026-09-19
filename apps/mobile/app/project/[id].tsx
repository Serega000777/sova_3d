import type {
  AIRequest,
  EditBody,
  EngineeringAnswer,
  Job,
  PrintAnalysis,
  ProjectSummary,
  RegionSelection,
  SplitProvenance,
  Version,
} from "@physical-ai/contracts";
import { Stack, useLocalSearchParams } from "expo-router";
import * as Linking from "expo-linking";
import { useCallback, useEffect, useState } from "react";
import {
  Image,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";

import { probe } from "@/src/capabilities";
import { EngineerCard } from "@/src/EngineerCard";
import { type DrawMode, ModelViewer, type Size } from "@/src/ModelViewer";
import { describeScale, type PickedPhoto, pickPhoto, uploadPhoto } from "@/src/photo";
import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";
import { VoiceButton } from "@/src/VoiceButton";

/** A small, honest palette (F-034); the same one the web offers. */
const PALETTE = ["#ff5533", "#ffb020", "#35c48d", "#5b9cff", "#b06bff", "#f2f2f2", "#202020"];
const BRUSHES = [
  { label: "fine", mm: 2 },
  { label: "medium", mm: 5 },
  { label: "wide", mm: 12 },
];

/** How big an outline is, for the chip that confirms what was drawn. */
function regionSize(selection: RegionSelection): string {
  const region = selection.region;
  if (region.kind === "box") {
    return region.max_mm.map((v, i) => (v - region.min_mm[i]).toFixed(0)).join(" × ") + " mm";
  }
  const xs = region.points_mm.map((p) => p[0]);
  const ys = region.points_mm.map((p) => p[1]);
  const w = Math.max(...xs) - Math.min(...xs);
  const h = Math.max(...ys) - Math.min(...ys);
  return `${w.toFixed(0)} × ${h.toFixed(0)} mm on ${region.axis}`;
}

/** F-081: the parts a version was cut into, when it was made by cutting. */
function splitOf(version: Version | null): SplitProvenance | null {
  return (version?.provenance as { split?: SplitProvenance } | undefined)?.split ?? null;
}

/** F-036: the other bodies of a version built as several — an enclosure's lid. */
function partsOf(version: Version | null): { name: string; asset_id: string; extents_mm?: number[] }[] {
  const parts = (version?.provenance as { parts?: { name: string; asset_id: string; extents_mm?: number[] }[] } | undefined)
    ?.parts;
  return Array.isArray(parts) ? parts.filter((part) => part?.asset_id) : [];
}

/** The kernel body the version's model was built from; edits target it by id (T-049).
 *  A plan that expects several bodies (a tray and its lid, F-036) shows the first one. */
function bodyOf(version: Version | null): string {
  const provenance = version?.provenance as
    | { bodies?: { name?: string }[]; expected_outputs?: string[] }
    | undefined;
  const expected = provenance?.expected_outputs?.[0];
  if (expected) return expected;
  const bodies = provenance?.bodies ?? [];
  return bodies[bodies.length - 1]?.name ?? "body";
}

export default function ProjectScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { client, session } = useSession();
  const capabilities = probe();

  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [active, setActive] = useState<Version | null>(null);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<PrintAnalysis | null>(null);
  const [size, setSize] = useState<Size | null>(null);
  const [selected, setSelected] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [pending, setPending] = useState<AIRequest | null>(null);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // F-019: a photo of the object goes in with the words; what in it has a known size.
  const [photo, setPhoto] = useState<PickedPhoto | null>(null);
  const [reference, setReference] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [mode, setMode] = useState<DrawMode>("orbit");
  const [handsFree, setHandsFree] = useState(false);
  const [region, setRegion] = useState<RegionSelection | null>(null);
  const [colour, setColour] = useState(PALETTE[0]);
  const [brush, setBrush] = useState(BRUSHES[1].mm);
  const [strokes, setStrokes] = useState<{ colour: string; region: RegionSelection }[]>([]);

  const refresh = useCallback(async () => {
    if (!client || !id) return;
    try {
      const summary = await client.getProject(id);
      setProject(summary);
      const list = await client.listVersions(id);
      setVersions(list);
      setActive((current) => list.find((v) => v.id === current?.id) ?? summary.head_version ?? null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [client, id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // A painted version carries its colours in a preview; show that instead of the plain mesh.
  const painted = active?.assets.find((a) => a.role === "preview");
  const shown = painted ?? active?.assets.find((a) => a.role === "model") ?? active?.assets[0];
  const shownAssetId = shown?.asset_id ?? null;
  const modelFormat: "stl" | "glb" = painted ? "glb" : "stl";
  const activeId = active?.id ?? null;

  useEffect(() => {
    if (!client || !activeId) {
      setModelUrl(null);
      setAnalysis(null);
      return;
    }
    let cancelled = false;
    if (shownAssetId) {
      void client.download(shownAssetId).then((d) => !cancelled && setModelUrl(d.url));
    } else {
      setModelUrl(null);
    }
    void client
      .listPrintAnalyses(activeId)
      .then((rows) => !cancelled && setAnalysis(rows[0] ?? null))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [client, activeId, shownAssetId]);

  useEffect(() => {
    setDraft(
      size
        ? {
            x: Number(size.x.toFixed(2)).toString(),
            y: Number(size.y.toFixed(2)).toString(),
            z: Number(size.z.toFixed(2)).toString(),
          }
        : {},
    );
  }, [size]);

  async function track(label: string, jobId: string): Promise<Job> {
    if (!client) throw new Error("not signed in");
    setBusy(label);
    try {
      return await client.waitForJob(jobId, {
        onProgress: (job) => setBusy(`${label} · ${job.progress}%`),
      });
    } finally {
      setBusy(null);
    }
  }

  /** Show what a job made: its version when it made one (a branch is not the head). */
  async function headAfterJob(job?: Job) {
    if (!client || !id) return;
    await refresh();
    const result = job?.result as {
      version_id?: string;
      paint?: { unused_strokes?: number[] } | null;
      scale?: { source: string; confidence: string; basis?: string } | null;
    } | null;
    // T-115: an edit re-applies the paint; say so when part of it no longer lands.
    const lost = result?.paint?.unused_strokes?.length ?? 0;
    // F-019: a photo-built model says where its size came from.
    setNotice(
      [
        lost ? `${lost} paint stroke(s) no longer land on the new shape` : null,
        describeScale(result?.scale),
      ]
        .filter(Boolean)
        .join(" · ") || null,
    );
    const made = result?.version_id;
    if (made) {
      setActive(await client.getVersion(made));
      return;
    }
    const summary = await client.getProject(id);
    setActive(summary.head_version ?? null);
  }

  /** F-019: the camera (or the photo library) — the picker keeps the file small. */
  async function takePhoto(source: "camera" | "library") {
    setError(null);
    try {
      const picked = await pickPhoto(source);
      if (picked) setPhoto(picked);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function send(spoken?: string) {
    const typed = (spoken ?? prompt).trim();
    const text = typed || (photo ? "Смоделируй предмет с фото" : "");
    if (!client || !session || !id || !text) return;
    setError(null);
    try {
      let imageAssetIds: string[] = [];
      if (photo) {
        setBusy("Uploading the photo");
        imageAssetIds = [await uploadPhoto(client, session.workspaceId, photo)];
      }
      const accepted = await client.createAiCommand(id, {
        prompt: text,
        units: "mm",
        target: "print",
        selection_entity_ids: selected ? [bodyOf(active)] : [],
        project_version_id: active?.id ?? null,
        preview: false, // the phone keeps it simple: build it and keep it
        region, // T-105: the outline, if one was drawn
        image_asset_ids: imageAssetIds,
        reference: reference.trim() || null,
      });
      const job = await track("Planning & building", accepted.job_id);
      setPhoto(null);
      setReference("");
      if (job.status === "waiting_input") {
        setPending(await client.getAiRequest(accepted.ai_request_id));
        return;
      }
      setPending(null);
      setPrompt("");
      setRegion(null);
      setMode("orbit");
      if (job.status === "failed") {
        setError((job.error as { message?: string })?.message ?? "the command failed");
      }
      await headAfterJob(job);
    } catch (err) {
      setBusy(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** T-109: the strokes go to the worker; the colours come back as a new version. */
  async function applyPaint() {
    if (!client || !active || !strokes.length) return;
    setError(null);
    try {
      const accepted = await client.paintModel(active.id, {
        strokes: strokes.map((stroke) => ({ colour: stroke.colour, region: stroke.region.region })),
        label: `Paint · ${new Set(strokes.map((s) => s.colour)).size} colour(s)`,
      });
      const job = await track("Painting", accepted.job_id);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string })?.message ?? "the paint did not land");
        return;
      }
      setStrokes([]);
      setMode("orbit");
      await headAfterJob(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function reply() {
    if (!client || !pending || !answer.trim()) return;
    try {
      const accepted = await client.clarify(pending.id, [answer.trim()]);
      setAnswer("");
      const job = await track("Continuing", accepted.job_id);
      if (job.status === "waiting_input") {
        setPending(await client.getAiRequest(pending.id));
        return;
      }
      setPending(null);
      await headAfterJob(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function resize() {
    if (!client || !active || !size) return;
    const fields: Record<string, number> = {};
    for (const [key, field] of [
      ["x", "width_mm"],
      ["y", "depth_mm"],
      ["z", "height_mm"],
    ] as const) {
      const value = Number(draft[key]);
      if (Number.isFinite(value) && value > 0 && Math.abs(value - size[key]) > 0.005) {
        fields[field] = value;
      }
    }
    if (!Object.keys(fields).length) return;
    setError(null);
    try {
      const accepted = await client.createEdit(active.id, {
        operations: [{ type: "set_dimensions", target: bodyOf(active), ...fields }],
        label: "Resize",
      });
      const job = await track("Resizing", accepted.job_id);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string })?.message ?? "the edit failed");
        return;
      }
      await headAfterJob(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** F-016: an earlier version becomes the current one — as a new version on top. */
  async function restoreVersion(version: Version) {
    if (!client || !id) return;
    setError(null);
    setBusy("Restoring");
    try {
      const restored = await client.rollback(id, `v${version.sequence_no}`);
      await refresh();
      setActive(restored);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  /** T-119: ask the engineer about the version (and the outlined area, if any). */
  async function askEngineer(body: {
    question: string | null;
    purpose: string | null;
    material_id: string;
  }): Promise<Job | null> {
    if (!client || !active) return null;
    setError(null);
    try {
      const accepted = await client.askEngineer(active.id, { ...body, region });
      const job = await track("Measuring", accepted.job_id);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string })?.message ?? "the engineer could not answer");
        return null;
      }
      return job;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }

  /** The engineer's fix is an ordinary edit: the same operations, the same kernel. */
  async function applyFix(fix: NonNullable<EngineeringAnswer["fix"]>) {
    if (!client || !active) return;
    setError(null);
    try {
      const accepted = await client.createEdit(active.id, {
        operations: fix.operations as EditBody["operations"],
        label: fix.label,
      });
      const job = await track("Applying the fix", accepted.job_id);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string })?.message ?? "the fix failed");
        return;
      }
      await headAfterJob(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function analyze() {
    if (!client || !active) return;
    setError(null);
    try {
      const accepted = await client.analyzePrint(active.id);
      await track("Checking printability", accepted.job_id);
      setAnalysis((await client.listPrintAnalyses(active.id))[0] ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const report = analysis?.report as
    | {
        score?: { total: number; status: string };
        summary?: string;
        warnings?: { code: string; message: string }[];
      }
    | undefined;

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={false} onRefresh={refresh} />}
    >
      <Stack.Screen options={{ title: project?.name ?? "Project" }} />

      <ModelViewer
        url={modelUrl}
        format={modelFormat}
        bodyId={bodyOf(active)}
        selected={selected}
        onSelect={setSelected}
        onMeasure={setSize}
        mode={mode}
        paintColour={colour}
        brushMm={brush}
        onRegion={(next) => {
          if (mode === "paint") {
            if (next) setStrokes((all) => [...all, { colour, region: next }]);
          } else {
            setRegion(next);
          }
        }}
      />

      <View style={styles.row}>
        <Pressable
          style={[styles.button, mode === "outline" && styles.buttonPrimary, !modelUrl && { opacity: 0.5 }]}
          disabled={!modelUrl}
          onPress={() => {
            setMode((m) => (m === "outline" ? "orbit" : "outline"));
            setRegion(null);
          }}
        >
          <Text style={styles.buttonText}>{mode === "outline" ? "Outlining…" : "Outline an area"}</Text>
        </Pressable>
        <Pressable
          style={[styles.button, mode === "paint" && styles.buttonPrimary, !modelUrl && { opacity: 0.5 }]}
          disabled={!modelUrl}
          onPress={() => {
            setMode((m) => (m === "paint" ? "orbit" : "paint"));
            setRegion(null);
          }}
        >
          <Text style={styles.buttonText}>{mode === "paint" ? "Painting…" : "Paint"}</Text>
        </Pressable>
        {region && mode !== "paint" && (
          <Pressable style={styles.chip} onPress={() => setRegion(null)}>
            <Text style={[styles.chipText, { color: colors.accent }]}>
              region {regionSize(region)} · ×
            </Text>
          </Pressable>
        )}
      </View>

      {mode === "paint" && (
        <View style={styles.card}>
          <Text style={styles.heading}>Paint</Text>
          <View style={styles.row}>
            {PALETTE.map((swatch) => (
              <Pressable
                key={swatch}
                accessibilityLabel={swatch}
                onPress={() => setColour(swatch)}
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: 8,
                  backgroundColor: swatch,
                  borderWidth: 2,
                  borderColor: colour === swatch ? colors.accent : colors.border,
                }}
              />
            ))}
          </View>
          <View style={styles.row}>
            {BRUSHES.map((option) => (
              <Pressable
                key={option.mm}
                style={[styles.button, brush === option.mm && styles.buttonPrimary]}
                onPress={() => setBrush(option.mm)}
              >
                <Text style={styles.buttonText}>
                  {option.label} · {option.mm} mm
                </Text>
              </Pressable>
            ))}
          </View>
          <Text style={styles.muted}>
            Sweep with a finger or the pencil to paint a band; close a loop to fill it. The
            shape never changes — the paint is a new version on top of what is there.
          </Text>
          <View style={styles.row}>
            <Text style={styles.muted}>
              {strokes.length} stroke{strokes.length === 1 ? "" : "s"}
            </Text>
            <Pressable
              style={[styles.button, styles.buttonPrimary, (!strokes.length || busy) && { opacity: 0.5 }]}
              disabled={!strokes.length || Boolean(busy)}
              onPress={applyPaint}
            >
              <Text style={styles.buttonText}>Keep the paint</Text>
            </Pressable>
            <Pressable
              style={[styles.button, !strokes.length && { opacity: 0.5 }]}
              disabled={!strokes.length}
              onPress={() => setStrokes([])}
            >
              <Text style={styles.buttonText}>Start over</Text>
            </Pressable>
          </View>
          {busy && <Text style={styles.muted}>{busy}</Text>}
          {error && <Text style={styles.error}>{error}</Text>}
        </View>
      )}

      <View style={styles.card}>
        <Text style={styles.heading}>Describe what you want</Text>
        <TextInput
          style={[styles.input, { minHeight: 76 }]}
          multiline
          value={prompt}
          onChangeText={setPrompt}
          placeholder="Органайзер 200×100×50 мм с 6 секциями"
          placeholderTextColor={colors.muted}
        />
        <View style={styles.row}>
          <Pressable
            style={[styles.chip, photo && { borderColor: colors.accent }]}
            disabled={Boolean(busy)}
            onPress={() => void takePhoto(Platform.OS === "web" ? "library" : "camera")}
          >
            <Text style={[styles.chipText, photo && { color: colors.accent }]}>
              {photo ? "photo attached" : "📷 from a photo"}
            </Text>
          </Pressable>
          {Platform.OS !== "web" && !photo && (
            <Pressable
              style={styles.chip}
              disabled={Boolean(busy)}
              onPress={() => void takePhoto("library")}
            >
              <Text style={styles.chipText}>from the library</Text>
            </Pressable>
          )}
          {photo && (
            <Pressable style={styles.chip} onPress={() => setPhoto(null)}>
              <Text style={styles.chipText}>remove</Text>
            </Pressable>
          )}
        </View>
        {photo && (
          <View style={styles.row}>
            <Image
              source={{ uri: photo.uri }}
              style={{ width: 64, height: 64, borderRadius: 6 }}
              accessibilityLabel="the attached photo"
            />
            <TextInput
              style={[styles.input, { flex: 1 }]}
              value={reference}
              onChangeText={setReference}
              placeholder="known size in the photo: “карта”, “ширина 80 мм”"
              placeholderTextColor={colors.muted}
            />
          </View>
        )}
        <View style={styles.row}>
          <Pressable
            style={[
              styles.button,
              styles.buttonPrimary,
              ((!prompt.trim() && !photo) || busy) && { opacity: 0.5 },
            ]}
            disabled={(!prompt.trim() && !photo) || Boolean(busy)}
            onPress={() => void send()}
          >
            <Text style={styles.buttonText}>Build</Text>
          </Pressable>
          <VoiceButton
            language="ru"
            disabled={Boolean(busy)}
            onText={setPrompt}
            onFinal={(text) => {
              setPrompt(text);
              if (handsFree) void send(text);
            }}
          />
          <Pressable style={styles.chip} onPress={() => setHandsFree((on) => !on)}>
            <Text style={[styles.chipText, handsFree && { color: colors.accent }]}>
              hands-free {handsFree ? "on" : "off"}
            </Text>
          </Pressable>
          {selected && <Text style={styles.muted}>scope: {bodyOf(active)}</Text>}
          {region && <Text style={styles.muted}>in the outlined area</Text>}
          {busy && <Text style={styles.muted}>{busy}</Text>}
        </View>
        {pending && (
          <View style={{ gap: 8 }}>
            {pending.clarifications.map((question) => (
              <Text key={question} style={[styles.text, { color: colors.yellow }]}>
                {question}
              </Text>
            ))}
            <TextInput
              style={styles.input}
              value={answer}
              onChangeText={setAnswer}
              placeholder="Your answer"
              placeholderTextColor={colors.muted}
            />
            <Pressable style={styles.button} onPress={reply} disabled={!answer.trim()}>
              <Text style={styles.buttonText}>Answer</Text>
            </Pressable>
          </View>
        )}
        {error && <Text style={styles.error}>{error}</Text>}
        {notice && <Text style={styles.muted}>{notice}</Text>}
      </View>

      {size && (
        <View style={styles.card}>
          <Text style={styles.heading}>Dimensions (mm)</Text>
          <View style={styles.row}>
            {(["x", "y", "z"] as const).map((axis) => (
              <TextInput
                key={axis}
                style={[styles.input, { flex: 1, minWidth: 80 }]}
                keyboardType="decimal-pad"
                value={draft[axis] ?? ""}
                onChangeText={(value) => setDraft((d) => ({ ...d, [axis]: value }))}
              />
            ))}
          </View>
          <Pressable
            style={[styles.button, styles.buttonPrimary, busy ? { opacity: 0.5 } : null]}
            disabled={Boolean(busy)}
            onPress={resize}
          >
            <Text style={styles.buttonText}>Apply size</Text>
          </Pressable>
        </View>
      )}

      {splitOf(active) && (
        <View style={styles.card}>
          <Text style={styles.heading}>Parts</Text>
          <Text style={styles.muted}>
            {splitOf(active)?.parts.length} parts
            {splitOf(active)?.dowels.length ? ` · ${splitOf(active)?.dowels.length} dowels` : ""}
            {" "}laid out on the plate — say “разрежь на 3 части” to cut any model
          </Text>
          {[...(splitOf(active)?.parts ?? []), ...(splitOf(active)?.dowels ?? [])].map((part) => (
            <View key={part.name} style={[styles.row, { justifyContent: "space-between" }]}>
              <Text style={styles.text}>
                {part.name}{" "}
                <Text style={styles.muted}>
                  {"extents_mm" in part
                    ? `${part.extents_mm.map((v) => v.toFixed(0)).join(" × ")} mm`
                    : `Ø${part.diameter_mm} × ${part.length_mm} mm`}
                </Text>
              </Text>
              <Pressable
                style={styles.chip}
                onPress={() => {
                  if (!client) return;
                  void client.download(part.asset_id).then((d) => Linking.openURL(d.url));
                }}
              >
                <Text style={styles.chipText}>STL</Text>
              </Pressable>
            </View>
          ))}
          {splitOf(active)?.warnings.map((warning) => (
            <Text key={warning} style={[styles.muted, { color: colors.yellow }]}>
              {warning}
            </Text>
          ))}
        </View>
      )}

      {partsOf(active).length > 0 && (
        <View style={styles.card}>
          <Text style={styles.heading}>Other bodies</Text>
          <Text style={styles.muted}>
            The viewer shows the main body; a case's lid is a file of its own — say “корпус под
            Raspberry Pi 4 с вентилятором” to build one
          </Text>
          {partsOf(active).map((part) => (
            <View key={part.name} style={[styles.row, { justifyContent: "space-between" }]}>
              <Text style={styles.text}>
                {part.name}{" "}
                {part.extents_mm && (
                  <Text style={styles.muted}>{part.extents_mm.map((v) => v.toFixed(0)).join(" × ")} mm</Text>
                )}
              </Text>
              <Pressable
                style={styles.chip}
                onPress={() => {
                  if (!client) return;
                  void client.download(part.asset_id).then((d) => Linking.openURL(d.url));
                }}
              >
                <Text style={styles.chipText}>STL</Text>
              </Pressable>
            </View>
          ))}
        </View>
      )}

      <EngineerCard
        disabled={!active || Boolean(busy)}
        hasRegion={region !== null}
        onAsk={askEngineer}
        onApplyFix={applyFix}
      />

      <View style={styles.card}>
        <Text style={styles.heading}>Print check</Text>
        {report?.score ? (
          <>
            <Text style={[styles.title, { color: colors.green }]}>
              {Math.round(report.score.total)}
              <Text style={styles.muted}> / 100 · {report.score.status}</Text>
            </Text>
            <Text style={styles.muted}>{report.summary}</Text>
            {report.warnings?.map((warning) => (
              <Text key={warning.code} style={[styles.muted, { color: colors.yellow }]}>
                {warning.message}
              </Text>
            ))}
          </>
        ) : (
          <Text style={styles.muted}>No analysis yet.</Text>
        )}
        <Pressable
          style={[styles.button, (!active || busy) && { opacity: 0.5 }]}
          disabled={!active || Boolean(busy)}
          onPress={analyze}
        >
          <Text style={styles.buttonText}>Analyze</Text>
        </Pressable>
      </View>

      <View style={styles.card}>
        <Text style={styles.heading}>Versions</Text>
        {active && project?.head_version && active.id !== project.head_version.id && (
          <Pressable
            style={[styles.button, busy ? { opacity: 0.5 } : null]}
            disabled={Boolean(busy)}
            onPress={() => void restoreVersion(active)}
          >
            <Text style={styles.buttonText}>Make v{active.sequence_no} current</Text>
          </Pressable>
        )}
        <Text style={styles.muted}>Or type it: «верни как было два часа назад», «undo».</Text>
        {versions.map((version) => (
          <Pressable
            key={version.id}
            onPress={() => setActive(version)}
            style={[
              styles.chip,
              { alignSelf: "flex-start" },
              version.id === active?.id && { borderColor: colors.accent },
            ]}
          >
            <Text style={styles.chipText}>
              v{version.sequence_no} · {version.label ?? "untitled"}
            </Text>
          </Pressable>
        ))}
      </View>

      <View style={styles.card}>
        <Text style={styles.heading}>Scanning</Text>
        <Text style={styles.muted}>
          {capabilities.depthScan
            ? "Depth scanning is available on this device."
            : capabilities.depthScanReason}
        </Text>
      </View>
    </ScrollView>
  );
}
