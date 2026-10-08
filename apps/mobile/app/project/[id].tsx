import type {
  AIRequest,
  ComponentKind,
  EditBody,
  EngineeringAnswer,
  Job,
  MeshEditOperation,
  MeshEditReport,
  MeshSelection,
  ModellingGrid,
  PrintAnalysis,
  ProjectSummary,
  RegionSelection,
  SplitProvenance,
  Version,
} from "@physical-ai/contracts";
import {
  ApiError,
  defaultGrid,
  getProjectGoal,
  type LiveEvent,
  type LiveRoom,
  type Vec3,
} from "@physical-ai/contracts";
import { Stack, useLocalSearchParams } from "expo-router";
import * as Linking from "expo-linking";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Image,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";

import { probe } from "@/src/capabilities";
import { EditModeSheet } from "@/src/EditModeSheet";
import { EngineerCard } from "@/src/EngineerCard";
import { GridPanel } from "@/src/GridPanel";
import { useIsTablet } from "@/src/layout";
import { MeshLayersSheet } from "@/src/MeshLayersSheet";
import {
  type DirectMeshEditOperation,
  type DrawMode,
  type MobileComponentSelection,
  ModelViewer,
  type Size,
} from "@/src/ModelViewer";
import { describeScale, type PickedPhoto, pickPhotos, uploadPhoto } from "@/src/photo";
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
// Keep in step with services/api/app/ai/contract.py MAX_PHOTOS.
const MAX_COMMAND_PHOTOS = 4;

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
  const { id, goal: goalId } = useLocalSearchParams<{ id: string; goal?: string }>();
  const projectGoal = getProjectGoal(goalId);
  const { client, session } = useSession();
  const capabilities = probe();
  const isTablet = useIsTablet();
  const language: "ru" | "en" = "ru";
  const ru = language === "ru";

  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [active, setActive] = useState<Version | null>(null);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<PrintAnalysis | null>(null);
  const [size, setSize] = useState<Size | null>(null);
  const [selected, setSelected] = useState(false);
  const [prompt, setPrompt] = useState(projectGoal?.defaultPrompt.ru ?? "");
  const [pending, setPending] = useState<AIRequest | null>(null);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // F-019: ordered views of the object go in with the words; what in them has a known size.
  const [photos, setPhotos] = useState<PickedPhoto[]>([]);
  const [reference, setReference] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [mode, setMode] = useState<DrawMode>("orbit");
  const [handsFree, setHandsFree] = useState(false);
  const [region, setRegion] = useState<RegionSelection | null>(null);
  const [colour, setColour] = useState(PALETTE[0]);
  const [brush, setBrush] = useState(BRUSHES[1].mm);
  const [strokes, setStrokes] = useState<{ colour: string; region: RegionSelection }[]>([]);
  // T-207: a held finger on the model opens this instead of scrolling down to the prompt.
  const [quickEditOpen, setQuickEditOpen] = useState(false);
  const [quickEditText, setQuickEditText] = useState("");
  const [editSheetOpen, setEditSheetOpen] = useState(false);
  const [gridPanelOpen, setGridPanelOpen] = useState(false);
  const [layersOpen, setLayersOpen] = useState(false);
  const [componentKind, setComponentKind] = useState<ComponentKind>("face");
  const [multiSelect, setMultiSelect] = useState(false);
  const [componentSelection, setComponentSelection] =
    useState<MobileComponentSelection | null>(null);
  const [editOperation, setEditOperation] = useState<DirectMeshEditOperation | null>(null);
  const [editMagnitude, setEditMagnitude] = useState(1);
  const [grid, setGrid] = useState<ModellingGrid>(() => defaultGrid());
  const [meshEditReport, setMeshEditReport] = useState<MeshEditReport | null>(null);
  const [meshEditError, setMeshEditError] = useState<string | null>(null);
  const [organicPrompt, setOrganicPrompt] = useState(
    projectGoal?.workflow === "organic" ? projectGoal.defaultPrompt.ru : "",
  );
  const [organicSize, setOrganicSize] = useState("60");
  const [organicQuality, setOrganicQuality] = useState<"fast" | "quality">("fast");

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

  // F-018: the same live room as the web studio — who else has the project open, and a
  // refresh the moment anyone (or any job) makes a new version.
  const [together, setTogether] = useState(0);
  const liveRoom = useRef<LiveRoom | null>(null);
  const lastPoint = useRef<Vec3 | null>(null);
  const [liveColours, setLiveColours] = useState<Record<string, string>>({});
  const [liveCursors, setLiveCursors] = useState<Record<string, Vec3>>({});
  const [liveNotes, setLiveNotes] = useState<Extract<LiveEvent, { type: "note" }>[]>([]);
  const [noteText, setNoteText] = useState("");
  useEffect(() => {
    if (!client?.token || !id) return;
    let others = new Set<string>();
    let mine: string | null = null;
    let me: string | null = null;
    const room = client.liveRoom(id, (event) => {
      if (event.type === "welcome") {
        mine = event.you.session;
        me = event.you.user_id;
        others = new Set(event.members.map((m) => m.session).filter((s) => s !== mine));
        setLiveColours(Object.fromEntries(event.members.map((m) => [m.session, m.colour])));
      } else if (event.type === "join" && event.session !== mine) {
        others.add(event.session);
        setLiveColours((all) => ({ ...all, [event.session]: event.member.colour }));
      } else if (event.type === "leave") {
        others.delete(event.session);
        setLiveCursors(({ [event.session]: _gone, ...rest }) => rest);
      } else if (event.type === "cursor") {
        setLiveCursors(({ [event.session]: _old, ...rest }) =>
          event.point ? { ...rest, [event.session]: event.point } : rest,
        );
      } else if (event.type === "note") {
        setLiveNotes((notes) => [event, ...notes].slice(0, 20));
      } else if (event.type === "version") {
        void refresh();
        if (event.created_by && event.created_by !== me) {
          setNotice(`Новая версия от коллеги: v${event.sequence_no}${event.label ? ` · ${event.label}` : ""}`);
        }
      }
      setTogether(others.size);
    });
    liveRoom.current = room;
    return () => {
      room.close();
      liveRoom.current = null;
    };
  }, [client, id, refresh]);
  const liveMarkers = [
    ...Object.entries(liveCursors).map(([session, point]) => ({
      key: `cursor-${session}`,
      colour: liveColours[session] ?? "#ffffff",
      point,
      kind: "cursor" as const,
    })),
    ...liveNotes
      .filter((note) => note.point)
      .map((note, index) => ({
        key: `note-${note.at}-${index}`,
        colour: note.member.colour,
        point: note.point as Vec3,
        kind: "note" as const,
      })),
  ];

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

  async function track(label: string, jobId: string, timeoutMs?: number): Promise<Job> {
    if (!client) throw new Error("not signed in");
    setBusy(label);
    try {
      return await client.waitForJob(jobId, {
        timeoutMs,
        intervalMs: timeoutMs ? 3000 : undefined,
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

  /** F-019: the camera or library adds ordered views; the picker keeps each file small. */
  async function takePhotos(source: "camera" | "library") {
    setError(null);
    try {
      const available = MAX_COMMAND_PHOTOS - photos.length;
      if (available <= 0) return;
      const picked = await pickPhotos(source, available);
      if (picked.length) {
        setPhotos((current) => [...current, ...picked].slice(0, MAX_COMMAND_PHOTOS));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function send(spoken?: string) {
    const typed = (spoken ?? prompt).trim();
    const text = typed || (photos.length ? "Смоделируй предмет с фото" : "");
    if (!client || !session || !id || !text) return;
    setError(null);
    try {
      let imageAssetIds: string[] = [];
      if (photos.length) {
        for (const [index, photo] of photos.entries()) {
          setBusy(`Загружаю фото ${index + 1} из ${photos.length}…`);
          imageAssetIds.push(await uploadPhoto(client, session.workspaceId, photo));
        }
      }
      const accepted = await client.createAiCommand(id, {
        prompt: text,
        units: "mm",
        target: projectGoal?.target ?? "print",
        selection_entity_ids: selected ? [bodyOf(active)] : [],
        project_version_id: active?.id ?? null,
        preview: false, // the phone keeps it simple: build it and keep it
        region, // T-105: the outline, if one was drawn
        image_asset_ids: imageAssetIds,
        reference: reference.trim() || null,
      });
      const job = await track(ru ? "Планируем и строим" : "Planning & building", accepted.job_id);
      setPhotos([]);
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
        setError(
          (job.error as { message?: string })?.message ??
            (ru ? "не удалось выполнить команду" : "the command failed"),
        );
      }
      await headAfterJob(job);
    } catch (err) {
      setBusy(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** F-001: a figurine or a vase from words — a learned guess at a shape, not a part. */
  async function generateOrganic() {
    const text = organicPrompt.trim();
    const sizeMm = Number(organicSize.replace(",", "."));
    if (!client || !id || !text) return;
    if (!(sizeMm >= 5 && sizeMm <= 1000)) {
      setError("Размер — от 5 до 1000 мм");
      return;
    }
    setError(null);
    try {
      const accepted = await client.generateMesh(id, {
        prompt: text,
        size_mm: sizeMm,
        quality: organicQuality,
      });
      const job = await track("Генерируем форму", accepted.job_id, 90 * 60_000);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string } | null)?.message ?? "не удалось сгенерировать");
        return;
      }
      setOrganicPrompt("");
      await headAfterJob(job);
      if (((job.result as { warnings?: string[] } | null)?.warnings ?? []).length) {
        setNotice("Модель понимает описания на английском — на другом языке форма непредсказуема.");
      }
    } catch (err) {
      setBusy(null);
      setError(
        err instanceof ApiError && err.code === "mesh_generation_not_enabled"
          ? "Генерация органики выключена на сервере."
          : err instanceof Error
            ? err.message
            : String(err),
      );
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
      const job = await track(ru ? "Красим" : "Painting", accepted.job_id);
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string })?.message ??
            (ru ? "не удалось нанести краску" : "the paint did not land"),
        );
        return;
      }
      setStrokes([]);
      setMode("orbit");
      await headAfterJob(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** Increment 1 direct mesh edit: the same versioned worker path and report as web. */
  async function runMeshEdit() {
    if (!client || !active || !componentSelection || !editOperation) return;
    const selection = componentSelection.selection;
    let operation: MeshEditOperation;
    if (editOperation === "move") {
      operation = { op: "move", selection, along_normal_mm: editMagnitude };
    } else if (editOperation === "extrude") {
      operation = {
        op: "extrude",
        selection: selection as MeshSelection & { kind: "face" },
        distance_mm: editMagnitude,
      };
    } else if (editOperation === "inset") {
      operation = {
        op: "inset",
        selection: selection as MeshSelection & { kind: "face" },
        amount_mm: editMagnitude,
      };
    } else if (editOperation === "bevel_edges") {
      operation = {
        op: "bevel_edges",
        selection: selection as MeshSelection & { kind: "edge" },
        width_mm: Math.abs(editMagnitude),
        segments: 1,
      };
    } else {
      operation = {
        op: "delete_faces",
        selection: selection as MeshSelection & { kind: "face" },
        fill: true,
      };
    }

    setError(null);
    setMeshEditError(null);
    setMeshEditReport(null);
    try {
      const accepted = await client.editMesh(active.id, {
        operations: [operation],
        expected_faces: componentSelection.expectedFaces,
        label: `Mobile mesh edit · ${editOperation}`,
      });
      const job = await track(ru ? "Редактируем сетку" : "Editing mesh", accepted.job_id);
      const report = (job.result as { report?: MeshEditReport } | null)?.report ?? null;
      setMeshEditReport(report);
      if (job.status !== "succeeded" || (report && !report.ok)) {
        const failure = job.error as { message?: string } | null;
        const message =
          report?.message ??
          failure?.message ??
          (ru ? "не удалось отредактировать сетку" : "the mesh edit failed");
        setMeshEditError(message);
        setError(message);
        return;
      }
      await headAfterJob(job);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setMeshEditError(message);
      setError(message);
    }
  }

  async function finishLayersJob(jobId: string) {
    const job = await track(ru ? "Перестраиваем слои сетки" : "Rebuilding mesh layers", jobId);
    if (job.status !== "succeeded") {
      const message =
        (job.error as { message?: string } | null)?.message ??
        (ru ? "не удалось перестроить слои" : "the layers did not rebuild");
      setError(message);
      throw new Error(message);
    }
    await headAfterJob(job);
  }

  async function reply() {
    if (!client || !pending || !answer.trim()) return;
    try {
      const accepted = await client.clarify(pending.id, [answer.trim()]);
      setAnswer("");
      const job = await track(ru ? "Продолжаем" : "Continuing", accepted.job_id);
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
      const job = await track(ru ? "Меняем размер" : "Resizing", accepted.job_id);
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string })?.message ??
            (ru ? "не удалось применить правку" : "the edit failed"),
        );
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
    setBusy(ru ? "Восстанавливаем" : "Restoring");
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
      const job = await track(ru ? "Измеряем" : "Measuring", accepted.job_id);
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string })?.message ??
            (ru ? "инженер не смог ответить" : "the engineer could not answer"),
        );
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
      const job = await track(ru ? "Применяем исправление" : "Applying the fix", accepted.job_id);
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string })?.message ??
            (ru ? "не удалось применить исправление" : "the fix failed"),
        );
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
      await track(ru ? "Проверяем пригодность к печати" : "Checking printability", accepted.job_id);
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
      <Stack.Screen
        options={{
          title: project?.name ?? "Project",
          headerRight: together > 0 ? () => <Text style={styles.muted}>+{together} в проекте</Text> : undefined,
        }}
      />

      <ModelViewer
        url={modelUrl}
        format={modelFormat}
        height={isTablet ? 520 : 320}
        bodyId={bodyOf(active)}
        selected={selected}
        onSelect={setSelected}
        onMeasure={setSize}
        mode={mode}
        componentKind={componentKind}
        multiSelect={multiSelect}
        grid={grid}
        activeEditOperation={editOperation}
        editMagnitude={editMagnitude}
        onEditMagnitudeChange={setEditMagnitude}
        onComponentSelection={(next) => {
          setComponentSelection(next);
          if (next) setEditSheetOpen(true);
        }}
        paintColour={colour}
        brushMm={brush}
        markers={liveMarkers}
        onPoint={(point) => {
          lastPoint.current = point ?? lastPoint.current;
          liveRoom.current?.pointAt(point);
        }}
        onRegion={(next) => {
          if (mode === "paint") {
            if (next) setStrokes((all) => [...all, { colour, region: next }]);
          } else {
            setRegion(next);
          }
        }}
        onQuickEdit={() => setQuickEditOpen(true)}
      />

      <EditModeSheet
        visible={editSheetOpen}
        language={language}
        kind={componentKind}
        multiSelect={multiSelect}
        selectedCount={componentSelection?.ids.length ?? 0}
        operation={editOperation}
        magnitude={editMagnitude}
        busy={Boolean(busy)}
        report={meshEditReport}
        error={meshEditError}
        onClose={() => setEditSheetOpen(false)}
        onKindChange={(kind) => {
          setComponentKind(kind);
          setComponentSelection(null);
          setEditOperation(null);
          setMeshEditReport(null);
          setMeshEditError(null);
        }}
        onMultiSelectChange={setMultiSelect}
        onOperationChange={(operation) => {
          setEditOperation(operation);
          setMeshEditReport(null);
          setMeshEditError(null);
        }}
        onMagnitudeChange={setEditMagnitude}
        onApply={() => void runMeshEdit()}
        onOpenLayers={() => {
          setEditSheetOpen(false);
          setLayersOpen(true);
        }}
      />

      <GridPanel
        visible={gridPanelOpen}
        language={language}
        grid={grid}
        onChange={setGrid}
        onClose={() => setGridPanelOpen(false)}
      />

      <MeshLayersSheet
        visible={layersOpen}
        language={language}
        client={client}
        versionId={activeId}
        busy={Boolean(busy)}
        onClose={() => setLayersOpen(false)}
        onJob={finishLayersJob}
      />

      <Modal
        visible={quickEditOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setQuickEditOpen(false)}
      >
        <Pressable
          style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" }}
          onPress={() => setQuickEditOpen(false)}
        >
          <Pressable style={[styles.card, { margin: 16 }]} onPress={(e) => e.stopPropagation()}>
            <Text style={styles.heading}>Что здесь исправить?</Text>
            <TextInput
              autoFocus
              style={styles.input}
              value={quickEditText}
              onChangeText={setQuickEditText}
              placeholder="Например: сделай стенки толще"
              placeholderTextColor={colors.muted}
            />
            <Pressable
              style={[styles.button, styles.buttonPrimary, !quickEditText.trim() && { opacity: 0.5 }]}
              disabled={!quickEditText.trim()}
              onPress={() => {
                const text = quickEditText.trim();
                setQuickEditOpen(false);
                setQuickEditText("");
                void send(text);
              }}
            >
              <Text style={styles.buttonText}>Исправить</Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>

      <View style={styles.row}>
        <Pressable
          style={[styles.button, mode === "outline" && styles.buttonPrimary, !modelUrl && { opacity: 0.5 }]}
          disabled={!modelUrl}
          onPress={() => {
            setMode((m) => (m === "outline" ? "orbit" : "outline"));
            setEditSheetOpen(false);
            setRegion(null);
          }}
        >
          <Text style={styles.buttonText}>
            {mode === "outline"
              ? ru
                ? "Выделяем…"
                : "Outlining…"
              : ru
                ? "Выделить область"
                : "Outline an area"}
          </Text>
        </Pressable>
        <Pressable
          style={[styles.button, mode === "paint" && styles.buttonPrimary, !modelUrl && { opacity: 0.5 }]}
          disabled={!modelUrl}
          onPress={() => {
            setMode((m) => (m === "paint" ? "orbit" : "paint"));
            setEditSheetOpen(false);
            setRegion(null);
          }}
        >
          <Text style={styles.buttonText}>
            {mode === "paint" ? (ru ? "Красим…" : "Painting…") : ru ? "Покрасить" : "Paint"}
          </Text>
        </Pressable>
        <Pressable
          style={[styles.button, mode === "edit" && styles.buttonPrimary, !modelUrl && { opacity: 0.5 }]}
          disabled={!modelUrl}
          onPress={() => {
            setMode("edit");
            setEditSheetOpen(true);
            setRegion(null);
          }}
        >
          <Text style={styles.buttonText}>
            {mode === "edit"
              ? ru
                ? "Редактируем сетку…"
                : "Editing mesh…"
              : ru
                ? "Править сетку"
                : "Edit mesh"}
          </Text>
        </Pressable>
        <Pressable
          style={[styles.button, !modelUrl && { opacity: 0.5 }]}
          disabled={!modelUrl}
          onPress={() => setGridPanelOpen(true)}
        >
          <Text style={styles.buttonText}>{ru ? "Сетка" : "Grid"}</Text>
        </Pressable>
        <Pressable
          style={[styles.button, !active && { opacity: 0.5 }]}
          disabled={!active}
          onPress={() => setLayersOpen(true)}
        >
          <Text style={styles.buttonText}>{ru ? "Слои" : "Layers"}</Text>
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
            style={[styles.chip, photos.length > 0 && { borderColor: colors.accent }]}
            disabled={Boolean(busy) || photos.length >= MAX_COMMAND_PHOTOS}
            onPress={() => void takePhotos(Platform.OS === "web" ? "library" : "camera")}
          >
            <Text style={[styles.chipText, photos.length > 0 && { color: colors.accent }]}>
              {photos.length
                ? `📷 прикреплено: ${photos.length}/${MAX_COMMAND_PHOTOS}`
                : "📷 снять фото"}
            </Text>
          </Pressable>
          {Platform.OS !== "web" && photos.length < MAX_COMMAND_PHOTOS && (
            <Pressable
              style={styles.chip}
              disabled={Boolean(busy)}
              onPress={() => void takePhotos("library")}
            >
              <Text style={styles.chipText}>из галереи</Text>
            </Pressable>
          )}
        </View>
        {photos.length < 3 && (
          <Text style={styles.muted}>
            Добавьте ещё один ракурс для более точного результата.
          </Text>
        )}
        {photos.length > 0 && (
          <>
            <View style={styles.row}>
              {photos.map((photo, index) => (
                <Pressable
                  key={`${photo.uri}-${index}`}
                  onPress={() => setPhotos((current) => current.filter((_, photoIndex) => photoIndex !== index))}
                  accessibilityRole="button"
                  accessibilityLabel={`Убрать фото ${index + 1}`}
                  style={{ alignItems: "center", gap: 2 }}
                >
                  <Image
                    source={{ uri: photo.uri }}
                    style={{ width: 64, height: 64, borderRadius: 6 }}
                    accessibilityLabel={`Прикреплённое фото ${index + 1}`}
                  />
                  <Text style={styles.chipText}>× убрать</Text>
                </Pressable>
              ))}
            </View>
            <TextInput
              style={styles.input}
              value={reference}
              onChangeText={setReference}
              placeholder="известный размер: «карта», «ширина 80 мм»"
              placeholderTextColor={colors.muted}
            />
          </>
        )}
        <View style={styles.row}>
          <Pressable
            style={[
              styles.button,
              styles.buttonPrimary,
              ((!prompt.trim() && photos.length === 0) || busy) && { opacity: 0.5 },
            ]}
            disabled={(!prompt.trim() && photos.length === 0) || Boolean(busy)}
            onPress={() => void send()}
          >
            <Text style={styles.buttonText}>Build</Text>
          </Pressable>
          <VoiceButton
            language={language}
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

      {(together > 0 || liveNotes.length > 0) && (
        <View style={styles.card}>
          <Text style={styles.heading}>Вместе · {together + 1} в проекте</Text>
          {liveNotes.slice(0, 5).map((note, index) => (
            <Text key={`${note.at}-${index}`} style={styles.muted}>
              <Text style={{ color: note.member.colour }}>● </Text>
              {note.member.name}: {note.text}
            </Text>
          ))}
          <View style={styles.row}>
            <TextInput
              style={[styles.input, { flex: 1 }]}
              value={noteText}
              onChangeText={setNoteText}
              maxLength={300}
              placeholder="Заметка к точке, куда вы коснулись модели"
              placeholderTextColor={colors.muted}
            />
            <Pressable
              style={[styles.button, !noteText.trim() && { opacity: 0.5 }]}
              disabled={!noteText.trim()}
              onPress={() => {
                liveRoom.current?.note(noteText.trim(), lastPoint.current);
                setNoteText("");
              }}
            >
              <Text style={styles.buttonText}>Отправить</Text>
            </Pressable>
          </View>
        </View>
      )}

      <View style={styles.card}>
        <Text style={styles.heading}>Органическая форма</Text>
        <TextInput
          style={styles.input}
          value={organicPrompt}
          onChangeText={setOrganicPrompt}
          maxLength={300}
          placeholder="по-английски: a small owl figurine"
          placeholderTextColor={colors.muted}
        />
        <View style={styles.row}>
          <TextInput
            style={[styles.input, { width: 90 }]}
            value={organicSize}
            onChangeText={setOrganicSize}
            keyboardType="decimal-pad"
            accessibilityLabel="размер по длинной стороне, мм"
          />
          <Text style={styles.muted}>мм по длинной стороне</Text>
          <Pressable
            style={[styles.button, (!organicPrompt.trim() || busy) && { opacity: 0.5 }]}
            disabled={!organicPrompt.trim() || Boolean(busy)}
            onPress={() => void generateOrganic()}
          >
            <Text style={styles.buttonText}>Сгенерировать</Text>
          </Pressable>
        </View>
        <View style={styles.row}>
          {(["fast", "quality"] as const).map((quality) => (
            <Pressable
              key={quality}
              style={[styles.button, organicQuality !== quality && { opacity: 0.55 }]}
              onPress={() => setOrganicQuality(quality)}
            >
              <Text style={styles.buttonText}>
                {quality === "fast" ? "Быстро · 16 шагов" : "Детальнее · 32 шага"}
              </Text>
            </Pressable>
          ))}
        </View>
        <Text style={styles.muted}>
          Быстрый режим экономит время и мелкие детали. 32 шага детальнее, но на CPU могут
          занять больше часа. Это догадка нейросети о форме, а не точная деталь.
        </Text>
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
        language={language}
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
