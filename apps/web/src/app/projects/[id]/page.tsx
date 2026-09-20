"use client";

import type {
  AIHistoryItem,
  AIRequest,
  EditBody,
  EngineeringAnswer,
  FitTestBody,
  FitTestReport,
  Job,
  Licence,
  LicenceTerms,
  Listing,
  ListingBody,
  PrinterProfile,
  Project,
  PrintAnalysis,
  ProjectSummary,
  ProvenanceGraph as GraphData,
  ReconstructionResult,
  RegionSelection,
  SplitBody,
  Version,
  VersionComparison,
} from "@physical-ai/contracts";
import dynamic from "next/dynamic";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { EngineerCard } from "@/components/EngineerCard";
import { FitTestCard } from "@/components/FitTestCard";
import { LicenceCard } from "@/components/LicenceCard";
import { ProvenanceGraph } from "@/components/ProvenanceGraph";
import { PublishCard } from "@/components/PublishCard";
import { PartsCard } from "@/components/PartsCard";
import { type CutPreview, SplitCard } from "@/components/SplitCard";
import { VoiceButton } from "@/components/VoiceButton";
import { Inspector, type Size } from "@/components/Inspector";
import { describeScale, shrinkPhoto } from "@/lib/photo";
import { useSession } from "@/lib/session";

const ModelViewer = dynamic(
  () => import("@/components/ModelViewer").then((m) => m.ModelViewer),
  { ssr: false },
);

type Busy = { label: string; job?: Job } | null;

/** The outline's size in mm, for the chip next to the prompt (F-062). */
function regionSize(selection: RegionSelection): string {
  const region = selection.region;
  if (region.kind === "box") {
    const size = region.max_mm.map((value, index) => value - region.min_mm[index]);
    return size.map((value) => value.toFixed(0)).join(" × ") + " mm";
  }
  const xs = region.points_mm.map((point) => point[0]);
  const ys = region.points_mm.map((point) => point[1]);
  const width = Math.max(...xs) - Math.min(...xs);
  const depth = Math.max(...ys) - Math.min(...ys);
  return `${width.toFixed(0)} × ${depth.toFixed(0)} mm on ${region.axis}`;
}

/** A small, honest palette; the colour input covers everything else (F-034). */
const PALETTE = ["#ff5533", "#ffb020", "#35c48d", "#5b9cff", "#b06bff", "#f2f2f2", "#202020"];
const BRUSHES = [
  { label: "fine", mm: 2 },
  { label: "medium", mm: 5 },
  { label: "wide", mm: 12 },
];

type Tool =
  | "chat"
  | "shape"
  | "detail"
  | "photo"
  | "region"
  | "paint"
  | "size"
  | "reverse"
  | "engineer"
  | "fit"
  | "parts"
  | "print"
  | "export"
  | "versions"
  | "history"
  | "origin"
  | "licence"
  | "market";

/** First-run prompts (T-098): a new project is a blank page until it suggests something. */
const EXAMPLES = [
  "Органайзер 200×100×50 мм с 6 секциями, скругление 1.5 мм",
  "Bracket 60x40x8 mm with 2 holes 5 mm",
  "Cylinder diameter 40 mm, height 20 mm",
];

/** The kernel body name the version's model was built from; edits target it by id (T-049).
 *  A plan that expects several bodies (a tray and its lid, F-036) shows the first one. */
function bodyOf(version: Version): string {
  const provenance = version.provenance as {
    bodies?: { name?: string }[];
    expected_outputs?: string[];
  } | null;
  const expected = provenance?.expected_outputs?.[0];
  if (expected) return expected;
  const bodies = provenance?.bodies ?? [];
  return bodies[bodies.length - 1]?.name ?? "body";
}

function statusClass(status: string | undefined): string {
  return status ? `status-${status}` : "";
}

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const templateId = search.get("template");
  const [nextSteps, setNextSteps] = useState<string[]>([]);
  const [others, setOthers] = useState<Project[]>([]);
  const router = useRouter();
  const [licences, setLicences] = useState<Licence[]>([]);
  const [terms, setTerms] = useState<LicenceTerms | null>(null);
  // F-017: with hands-free on, a finished sentence is sent without touching a key.
  const [handsFree, setHandsFree] = useState(false);
  const language: "ru" | "en" =
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru")
      ? "ru"
      : "en";
  const projectId = params.id;
  const { session, ready, client } = useSession();

  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [activeVersion, setActiveVersion] = useState<Version | null>(null);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [history, setHistory] = useState<AIHistoryItem[]>([]);
  const [analysis, setAnalysis] = useState<PrintAnalysis | null>(null);
  const [reconstruction, setReconstruction] = useState<ReconstructionResult | null>(null);
  const [reconstructionTolerance, setReconstructionTolerance] = useState(0.2);
  const [primitiveKind, setPrimitiveKind] = useState<"box" | "cylinder">("box");
  const [primitiveMode, setPrimitiveMode] = useState<"add" | "cut">("add");
  const [primitiveSize, setPrimitiveSize] = useState({ width: 40, depth: 40, height: 20, diameter: 30 });
  const [primitiveOrigin, setPrimitiveOrigin] = useState({ x: 0, y: 0, z: 0 });
  const [detailKind, setDetailKind] = useState<"hole" | "fillet" | "chamfer">("hole");
  const [holeAxis, setHoleAxis] = useState<"x" | "y" | "z">("z");
  const [holeSide, setHoleSide] = useState<"+" | "-">("+");
  const [holePosition, setHolePosition] = useState({ u: 20, v: 20 });
  const [holeDiameter, setHoleDiameter] = useState(5);
  const [holeThrough, setHoleThrough] = useState(true);
  const [holeDepth, setHoleDepth] = useState(10);
  const [edgeSize, setEdgeSize] = useState(2);
  const [selected, setSelected] = useState<string[]>([]);
  const [prompt, setPrompt] = useState(() => search.get("prompt") ?? "");
  // the studio: one tool panel open at a time, the chat by default
  const [tool, setTool] = useState<Tool | null>("chat");
  const [studioMode, setStudioMode] = useState<"simple" | "pro">("simple");
  const [showAllTools, setShowAllTools] = useState(false);
  const [displayMode, setDisplayMode] = useState<"solid" | "wire" | "xray">("solid");
  const [showGrid, setShowGrid] = useState(true);
  const [topOffset, setTopOffset] = useState(49); // the top bar's real height (it may wrap)
  useEffect(() => {
    const measure = () => {
      const bar = document.querySelector<HTMLElement>(".topbar");
      if (bar) setTopOffset(bar.offsetHeight);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  // F-075: the sentence the current sketches answer — "see others" asks it again
  const [sketchPrompt, setSketchPrompt] = useState<string>("");
  const autoSketches = useRef(search.get("auto") === "variants");
  const promptBox = useRef<HTMLTextAreaElement>(null);
  const [pending, setPending] = useState<AIRequest | null>(null);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [downloads, setDownloads] = useState<{ format: string; url: string }[]>([]);
  const [size, setSize] = useState<Size | null>(null);
  const [preview, setPreview] = useState<{ version: Version; diff: VersionComparison } | null>(
    null,
  );
  const [previewMode, setPreviewMode] = useState(false);
  // F-075: several answers to one request, each a preview; the user keeps one.
  const [variants, setVariants] = useState<
    { strategy: string; title: string; version: Version; size: number[] | null }[]
  >([]);
  const [regionMode, setRegionMode] = useState(false);
  const [region, setRegion] = useState<RegionSelection | null>(null);
  // F-019: a photo of the object goes in with the words; what in it has a known size.
  const [photo, setPhoto] = useState<{ blob: Blob; name: string; url: string } | null>(null);
  const [reference, setReference] = useState("");
  const photoInput = useRef<HTMLInputElement>(null);
  // F-081: the planned cuts, drawn on the model while the user chooses them.
  const [cutPlanes, setCutPlanes] = useState<CutPreview[]>([]);
  const [printers, setPrinters] = useState<PrinterProfile[]>([]);
  // F-004: what of this project is on the marketplace
  const [listings, setListings] = useState<Listing[]>([]);
  // F-079: where every version came from, drawn
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [showGraph, setShowGraph] = useState(false);
  const [paintMode, setPaintMode] = useState(false);
  const [colour, setColour] = useState(PALETTE[0]);
  const [brush, setBrush] = useState(BRUSHES[1].mm);
  const [strokes, setStrokes] = useState<{ colour: string; region: RegionSelection }[]>([]);

  const refresh = useCallback(async () => {
    if (!client) return;
    const summary = await client.getProject(projectId);
    setProject(summary);
    const list = await client.listVersions(projectId);
    setVersions(list);
    const requests = await client.listAiRequests(projectId);
    setHistory(requests);
    setListings(await client.projectListings(projectId).catch(() => []));
    setGraph(await client.projectGraph(projectId).catch(() => null));
    // F-073: a question the AI is still waiting on survives a reload or a change of device.
    const open = requests.find((h) => h.status === "needs_clarification");
    setPending(open ? await client.getAiRequest(open.id) : null);
    // nothing kept yet but sketches exist: show the latest one rather than an empty stage
    const head = summary.head_version ?? list[0] ?? null;
    setActiveVersion((current) => list.find((v) => v.id === current?.id) ?? head);
  }, [client, projectId]);

  useEffect(() => {
    void refresh().catch((err) => setError(String(err)));
  }, [refresh]);

  // F-072: the licence catalogue once, the project's terms whenever the project changes.
  useEffect(() => {
    if (!client) return;
    void client.listLicences().then(setLicences).catch(() => setLicences([]));
  }, [client]);
  // F-081: "fit my printer" needs a printer profile to fit.
  useEffect(() => {
    if (!client || !session) return;
    void client
      .listPrinterProfiles(session.workspaceId)
      .then(setPrinters)
      .catch(() => setPrinters([]));
  }, [client, session]);
  useEffect(() => {
    if (!client || !project) return;
    void client.projectLicense(project.id).then(setTerms).catch(() => setTerms(null));
  }, [client, project]);

  /** F-072: record where the work comes from. */
  async function saveLicense(body: {
    license_id: string | null;
    attribution: string | null;
    source_url: string | null;
  }) {
    if (!client) return;
    setError(null);
    try {
      await client.setProjectLicense(projectId, body);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** F-004: the current kept version goes on the shelf. */
  async function publishListing(body: ListingBody) {
    if (!client) return;
    setError(null);
    try {
      const listing = await client.publishListing(projectId, body);
      setNotice(`Listed on the marketplace as “${listing.title}” (${listing.license_name})`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function withdrawListing(listingId: string, back: boolean) {
    if (!client) return;
    setError(null);
    try {
      await client.updateListing(listingId, { status: back ? "published" : "withdrawn" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** F-047: a new project from this model, with the credit written — if the licence allows. */
  async function remix() {
    if (!client) return;
    setError(null);
    try {
      const copy = await client.remixProject(projectId);
      router.push(`/projects/${copy.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  // F-027: the other parts in the workspace, for the fit test.
  useEffect(() => {
    if (!client || !session) return;
    void client
      .listProjects(session.workspaceId)
      .then(setOthers)
      .catch(() => setOthers([]));
  }, [client, session]);

  // F-070: a project started from a template opens with what to try on it next.
  useEffect(() => {
    if (!client || !templateId) return;
    const ru = typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru");
    void client
      .listTemplates()
      .then((all) => {
        const found = all.find((t) => t.id === templateId);
        setNextSteps(found ? (ru ? found.next_steps_ru : found.next_steps_en) : []);
      })
      .catch(() => setNextSteps([]));
  }, [client, templateId]);

  // T-089: every accepted change is already a version server-side; poll so a version
  // created elsewhere (another device, a finished job) shows up without a reload.
  useEffect(() => {
    if (!client) return;
    const timer = setInterval(() => void refresh().catch(() => undefined), 15_000);
    return () => clearInterval(timer);
  }, [client, refresh]);

  // What the viewport shows: a painted version carries its colours in a preview, so that
  // wins over the plain mesh. Keyed by ids so the 15 s poll does not re-download the model.
  const painted = activeVersion?.assets.find((a) => a.role === "preview");
  const shown =
    painted ?? activeVersion?.assets.find((a) => a.role === "model") ?? activeVersion?.assets[0];
  const shownAssetId = shown?.asset_id ?? null;
  const modelFormat: "stl" | "glb" = painted ? "glb" : "stl";
  const activeVersionId = activeVersion?.id ?? null;

  // Load the active version's model + latest analysis.
  useEffect(() => {
    if (!client || !activeVersionId) {
      setModelUrl(null);
      setAnalysis(null);
      return;
    }
    if (!shownAssetId) {
      setModelUrl(null);
      return;
    }
    let cancelled = false;
    // a flaky local proxy must not become an uncaught error: the HUD says what happened
    void client
      .download(shownAssetId)
      .then((d) => !cancelled && setModelUrl(d.url))
      .catch((err: unknown) => {
        if (cancelled) return;
        setModelUrl(null);
        setError(`the model could not be fetched: ${err instanceof Error ? err.message : err}`);
      });
    void client
      .listPrintAnalyses(activeVersionId)
      .then((rows) => !cancelled && setAnalysis(rows[0] ?? null))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [client, activeVersionId, shownAssetId]);

  /** Show what a job made: its version when it made one (a branch is not the head). */
  async function showResult(job: Job) {
    if (!client) return;
    const result = job.result as {
      version_id?: string;
      paint?: { unused_strokes?: number[] } | null;
      scale?: { source: string; confidence: string; basis?: string } | null;
    } | null;
    // T-115: an edit re-applies the paint; say so when part of it no longer lands.
    const lost = result?.paint?.unused_strokes?.length ?? 0;
    const plural = lost === 1 ? "stroke no longer lands" : "strokes no longer land";
    // F-019: a photo-built model says where its size came from.
    setNotice(
      [lost ? `${lost} paint ${plural} on the new shape` : null, describeScale(result?.scale)]
        .filter(Boolean)
        .join(" · ") || null,
    );
    const made = result?.version_id;
    if (made) {
      setActiveVersion(await client.getVersion(made));
      return;
    }
    const summary = await client.getProject(projectId);
    setActiveVersion(summary.head_version ?? null);
  }

  async function trackJob(label: string, jobId: string): Promise<Job> {
    if (!client) throw new Error("not signed in");
    setBusy({ label });
    try {
      return await client.waitForJob(jobId, { onProgress: (job) => setBusy({ label, job }) });
    } finally {
      setBusy(null);
    }
  }

  /** F-019: a photo becomes an asset the planner may look at; the words say the rest. */
  async function attachPhoto(file: File) {
    setError(null);
    try {
      const blob = await shrinkPhoto(file);
      if (photo) URL.revokeObjectURL(photo.url);
      setPhoto({
        blob,
        name: file.name.replace(/\.[^.]+$/, "") + ".jpg",
        url: URL.createObjectURL(blob),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function dropPhoto() {
    if (photo) URL.revokeObjectURL(photo.url);
    setPhoto(null);
    setReference("");
  }

  async function sendCommand(event: FormEvent | null, spoken?: string) {
    event?.preventDefault();
    const typed = (spoken ?? prompt).trim();
    // a photo alone is a request too: "build what you see"
    const seeIt =
      language === "ru" ? "Смоделируй предмет с фото" : "Model the object in the photo";
    const text = typed || (photo ? seeIt : "");
    if (!client || !session || !text) return;
    setError(null);
    try {
      let imageAssetIds: string[] = [];
      if (photo) {
        setBusy({ label: "Uploading the photo" });
        const asset = await client.uploadFile(
          session.workspaceId,
          photo.blob,
          photo.name,
          "image/jpeg",
        );
        imageAssetIds = [asset.id];
      }
      const accepted = await client.createAiCommand(projectId, {
        prompt: text,
        units: "mm",
        target: "print",
        selection_entity_ids: selected,
        project_version_id: activeVersion?.id ?? null,
        preview: previewMode,
        region,
        image_asset_ids: imageAssetIds,
        reference: reference.trim() || null,
      });
      const job = await trackJob("Planning & building", accepted.job_id);
      await afterAiJob(accepted.ai_request_id, job);
      setPrompt("");
      dropPhoto();
      if (job.status === "succeeded") {
        setRegion(null);
        setRegionMode(false);
      }
    } catch (err) {
      setBusy(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function afterAiJob(requestId: string, job: Job) {
    if (!client) return;
    if (job.status === "waiting_input") {
      setPending(await client.getAiRequest(requestId));
      return;
    }
    setPending(null);
    if (job.status === "failed") {
      const detail = job.error as { message?: string } | null;
      setError(detail?.message ?? "the command failed");
    }
    await refresh();
    if (await showPreviewIfDraft(job)) return;
    await showResult(job);
  }

  /** T-052: a preview is built but not kept — show it next to what it would replace. */
  /** F-075: the same sentence answered three ways — previews to choose between. */
  async function buildVariants(sentence?: string) {
    const asked = (sentence ?? prompt).trim();
    if (!client || !asked) return;
    setError(null);
    setVariants([]);
    setSketchPrompt(asked);
    try {
      const accepted = await client.createVariants(projectId, {
        prompt: asked,
        count: 3,
        project_version_id: activeVersion?.id ?? null,
        selection_entity_ids: selected,
        region,
        target: "print",
      });
      setBusy({ label: language === "ru" ? "Готовим 3 эскиза" : "Building 3 sketches" });
      const jobs = await Promise.all(accepted.map((variant) => client.waitForJob(variant.job_id)));
      setBusy(null);
      const made: typeof variants = [];
      for (const [index, job] of jobs.entries()) {
        const result = job.result as {
          version_id?: string;
          bodies?: { bbox_mm?: { size?: number[] } }[];
        } | null;
        if (job.status !== "succeeded" || !result?.version_id) continue;
        const version = await client.getVersion(result.version_id);
        made.push({
          strategy: accepted[index].strategy,
          title: language === "ru" ? accepted[index].title_ru : accepted[index].title_en,
          version,
          size: result.bodies?.[result.bodies.length - 1]?.bbox_mm?.size ?? null,
        });
      }
      if (!made.length) {
        setError("none of the variants could be built");
        return;
      }
      setVariants(made);
      setActiveVersion(made[0].version);
      setPrompt("");
      await refresh();
    } catch (err) {
      setBusy(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  // "+ Создать модель" with a brief: the sketches start on their own, once
  useEffect(() => {
    if (!autoSketches.current || !client || !session || busy) return;
    autoSketches.current = false;
    const asked = search.get("prompt")?.trim();
    if (asked) void buildVariants(asked);
    // buildVariants closes over state that is fresh on this first run
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, session]);

  /** Keep one variant: it becomes the project; the other previews are discarded. */
  async function chooseVariant(chosen: Version) {
    if (!client) return;
    setError(null);
    try {
      await client.acceptVersion(chosen.id);
      for (const other of variants) {
        if (other.version.id !== chosen.id) await client.discardVersion(other.version.id);
      }
      setVariants([]);
      await refresh();
      setActiveVersion(await client.getVersion(chosen.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function showPreviewIfDraft(job: Job): Promise<boolean> {
    if (!client) return false;
    const result = job.result as { version_id?: string; preview?: boolean } | null;
    if (!result?.preview || !result.version_id) return false;
    const version = await client.getVersion(result.version_id);
    const diff = await client.compareVersion(version.id);
    setPreview({ version, diff });
    setActiveVersion(version);
    return true;
  }

  async function decidePreview(keep: boolean) {
    if (!client || !preview) return;
    setError(null);
    try {
      if (keep) await client.acceptVersion(preview.version.id);
      else await client.discardVersion(preview.version.id);
      setPreview(null);
      await refresh();
      const summary = await client.getProject(projectId);
      setActiveVersion(summary.head_version ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** The answer lives inside the command form (no nested <form>): Enter or the button sends it. */
  async function sendAnswer(event?: { preventDefault(): void }) {
    event?.preventDefault();
    if (!client || !pending || !answer.trim()) return;
    setError(null);
    try {
      const accepted = await client.clarify(pending.id, [answer.trim()]);
      setAnswer("");
      const job = await trackJob("Continuing", accepted.job_id);
      await afterAiJob(pending.id, job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function analyze() {
    if (!client || !activeVersion) return;
    setError(null);
    const accepted = await client.analyzePrint(activeVersion.id);
    const job = await trackJob("Checking printability", accepted.job_id);
    if (job.status === "failed") setError((job.error as { message?: string })?.message ?? "failed");
    setAnalysis((await client.listPrintAnalyses(activeVersion.id))[0] ?? null);
  }

  /** F-024/F-011: turn a triangle mesh into an editable feature tree, then measure it. */
  async function reconstructCad() {
    if (!client || !activeVersion) return;
    setError(null);
    setReconstruction(null);
    try {
      const accepted = await client.reconstruct(activeVersion.id, {
        tolerance_mm: reconstructionTolerance,
        threads: true,
      });
      const job = await trackJob(ru ? "Распознаём геометрию" : "Recognizing geometry", accepted.job_id);
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string } | null)?.message ??
            (ru ? "Не удалось реконструировать модель" : "The model could not be reconstructed"),
        );
        return;
      }
      setReconstruction(job.result as unknown as ReconstructionResult);
      await refresh();
      await showResult(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** F-061: start from an exact primitive or add/subtract one from the current body. */
  async function applyPrimitive() {
    if (!client) return;
    setError(null);
    try {
      let accepted;
      if (!activeVersion) {
        accepted = await client.createPrimitive(projectId, {
          kind: primitiveKind,
          width_mm: primitiveKind === "box" ? primitiveSize.width : null,
          depth_mm: primitiveKind === "box" ? primitiveSize.depth : null,
          height_mm: primitiveSize.height,
          diameter_mm: primitiveKind === "cylinder" ? primitiveSize.diameter : null,
        });
      } else {
        const suffix = `v${activeVersion.sequence_no + 1}`;
        const creator = `shape_${suffix}`;
        const origin: [number, number, number] = [primitiveOrigin.x, primitiveOrigin.y, primitiveOrigin.z];
        const create =
          primitiveKind === "box"
            ? {
                id: creator,
                type: "create_box",
                width_mm: primitiveSize.width,
                depth_mm: primitiveSize.depth,
                height_mm: primitiveSize.height,
                origin_mm: origin,
              }
            : {
                id: creator,
                type: "create_cylinder",
                diameter_mm: primitiveSize.diameter,
                height_mm: primitiveSize.height,
                axis: "z",
                origin_mm: origin,
              };
        accepted = await client.createEdit(activeVersion.id, {
          label: primitiveMode === "add" ? "Add primitive" : "Subtract primitive",
          preview: false,
          operations: [
            create,
            {
              id: `${primitiveMode}_${suffix}`,
              type: "boolean",
              op: primitiveMode === "add" ? "fuse" : "cut",
              target: bodyOf(activeVersion),
              tool: creator,
            },
          ],
        });
      }
      const job = await trackJob(
        activeVersion
          ? primitiveMode === "add"
            ? ru ? "Добавляем форму" : "Adding shape"
            : ru ? "Вырезаем форму" : "Cutting shape"
          : ru ? "Создаём форму" : "Creating shape",
        accepted.job_id,
      );
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string } | null)?.message ?? (ru ? "Операция не выполнена" : "Operation failed"));
        return;
      }
      await refresh();
      await showResult(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function applyDetail() {
    if (!client || !activeVersion) return;
    setError(null);
    const suffix = `v${activeVersion.sequence_no + 1}`;
    const target = bodyOf(activeVersion);
    const operation =
      detailKind === "hole"
        ? {
            id: `hole_${suffix}`,
            type: "add_hole",
            target,
            face: { kind: "face_by_normal", axis: holeAxis, sign: holeSide },
            position_mm: [holePosition.u, holePosition.v],
            diameter_mm: holeDiameter,
            depth_mm: holeThrough ? null : holeDepth,
          }
        : detailKind === "fillet"
          ? {
              id: `fillet_${suffix}`,
              type: "fillet",
              target,
              edges: { kind: "all_edges" },
              radius_mm: edgeSize,
            }
          : {
              id: `chamfer_${suffix}`,
              type: "chamfer",
              target,
              edges: { kind: "all_edges" },
              distance_mm: edgeSize,
            };
    try {
      const accepted = await client.createEdit(activeVersion.id, {
        label:
          detailKind === "hole"
            ? `Hole Ø${holeDiameter} mm`
            : detailKind === "fillet"
              ? `Fillet ${edgeSize} mm`
              : `Chamfer ${edgeSize} mm`,
        preview: false,
        operations: [operation],
      });
      const labels = {
        hole: ru ? "Сверлим отверстие" : "Adding hole",
        fillet: ru ? "Скругляем рёбра" : "Rounding edges",
        chamfer: ru ? "Добавляем фаску" : "Chamfering edges",
      };
      const job = await trackJob(labels[detailKind], accepted.job_id);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string } | null)?.message ?? (ru ? "Операция не выполнена" : "Operation failed"));
        return;
      }
      await refresh();
      await showResult(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function optimize(apply: boolean) {
    if (!client || !activeVersion) return;
    setError(null);
    const accepted = await client.optimizePrint(activeVersion.id, { apply });
    const job = await trackJob(apply ? "Applying best orientation" : "Finding best orientation", accepted.job_id);
    if (job.status === "failed") setError((job.error as { message?: string })?.message ?? "failed");
    await refresh();
    if (apply) {
      await showResult(job);
    } else {
      setAnalysis((await client.listPrintAnalyses(activeVersion.id))[0] ?? null);
    }
  }

  /** F-016: an earlier version becomes the current one — as a new version on top. */
  async function restoreVersion(version: Version) {
    if (!client) return;
    setError(null);
    setBusy({ label: "Restoring" });
    try {
      const restored = await client.rollback(projectId, `v${version.sequence_no}`);
      await refresh();
      setActiveVersion(restored);
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
    if (!client || !activeVersion) return null;
    setError(null);
    try {
      const accepted = await client.askEngineer(activeVersion.id, { ...body, region });
      const job = await trackJob("Measuring", accepted.job_id);
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

  /** F-027: put another project's model against this version. */
  async function runFitTest(body: Omit<FitTestBody, "version_a_id">): Promise<Job | null> {
    if (!client || !activeVersion) return null;
    setError(null);
    try {
      const accepted = await client.startFitTest({ ...body, version_a_id: activeVersion.id });
      const job = await trackJob("Fitting", accepted.job_id);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string })?.message ?? "the parts could not be fitted");
        return null;
      }
      return job;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }

  /** F-081: cut the model into printable parts — a version of parts, each one a file. */
  async function cutIntoParts(body: SplitBody) {
    if (!client || !activeVersion) return;
    setError(null);
    try {
      const accepted = await client.splitModel(activeVersion.id, body);
      const job = await trackJob("Cutting", accepted.job_id);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string })?.message ?? "the model could not be cut");
        return;
      }
      const result = job.result as { parts?: unknown[]; warnings?: string[] } | null;
      setCutPlanes([]);
      await refresh();
      await showResult(job);
      setNotice(
        [`${result?.parts?.length ?? 0} parts on the plate`, ...(result?.warnings ?? [])].join(" · "),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** A part's STL, opened the same way exports are. */
  async function downloadPart(assetId: string, name: string) {
    if (!client) return;
    try {
      const download = await client.download(assetId);
      setDownloads((d) => [{ format: name.includes(".") ? name : `${name}.stl`, url: download.url }, ...d]);
      window.open(download.url, "_blank", "noopener");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** F-009: the part adapts to a material — a preview you keep or discard. */
  async function adaptMaterial(materialId: string) {
    if (!client || !activeVersion) return;
    setError(null);
    try {
      const started = await client.adaptMaterial(activeVersion.id, {
        material_id: materialId,
        language,
        preview: true,
      });
      const report = started.report as { changes?: string[]; skipped?: string[] };
      setNotice([...(report.changes ?? []), ...(report.skipped ?? [])].join(" · "));
      const job = await trackJob("Adapting", started.job.job_id);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string })?.message ?? "the adaptation failed");
        return;
      }
      await refresh();
      if (await showPreviewIfDraft(job)) return;
      await showResult(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** F-007: hollow the part — a preview; the notice says what it weighs before and after. */
  async function lighten(materialId: string) {
    if (!client || !activeVersion) return;
    setError(null);
    try {
      const started = await client.optimizeModel(activeVersion.id, {
        goal: "lighter",
        material_id: materialId,
        language,
        preview: true,
      });
      const report = started.report as {
        changes?: string[];
        skipped?: string[];
        mass_before_g?: number;
        density_g_cm3?: number;
      };
      const job = await trackJob("Hollowing", started.job.job_id);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string })?.message ?? "the part could not be hollowed");
        return;
      }
      const bodies = (job.result as { bodies?: { volume_mm3?: number }[] } | null)?.bodies ?? [];
      const after = bodies[bodies.length - 1]?.volume_mm3;
      const mass =
        after !== undefined && report.density_g_cm3 && report.mass_before_g !== undefined
          ? `${report.mass_before_g} g → ${((after / 1000) * report.density_g_cm3).toFixed(1)} g`
          : null;
      setNotice(
        [mass, ...(report.changes ?? []), ...(report.skipped ?? [])].filter(Boolean).join(" · "),
      );
      await refresh();
      if (await showPreviewIfDraft(job)) return;
      await showResult(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** The engineer's fix is an ordinary edit: the same operations, the same kernel. */
  async function applyFix(fix: NonNullable<EngineeringAnswer["fix"] | FitTestReport["advice"]["fix"]>) {
    if (!client || !activeVersion) return;
    setError(null);
    try {
      const accepted = await client.createEdit(activeVersion.id, {
        operations: fix.operations as EditBody["operations"],
        label: fix.label,
        preview: previewMode,
      });
      const job = await trackJob("Applying the fix", accepted.job_id);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string })?.message ?? "the fix failed");
        return;
      }
      await refresh();
      if (await showPreviewIfDraft(job)) return;
      await showResult(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function applyDimensions(dimensions: {
    width_mm?: number;
    depth_mm?: number;
    height_mm?: number;
  }) {
    if (!client || !activeVersion) return;
    setError(null);
    const target = bodyOf(activeVersion);
    try {
      const accepted = await client.createEdit(activeVersion.id, {
        operations: [{ type: "set_dimensions", target, ...dimensions }],
        label: `Resize ${Object.values(dimensions).map((v) => `${v} mm`).join(" × ")}`,
        preview: previewMode,
      });
      const job = await trackJob("Resizing", accepted.job_id);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string })?.message ?? "the edit failed");
        return;
      }
      await refresh();
      if (await showPreviewIfDraft(job)) return;
      await showResult(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** T-109: send the strokes; the worker colours the mesh and the result is a new version. */
  async function applyPaint() {
    if (!client || !activeVersion || !strokes.length) return;
    setError(null);
    try {
      const accepted = await client.paintModel(activeVersion.id, {
        strokes: strokes.map((stroke) => ({ colour: stroke.colour, region: stroke.region.region })),
        label: `Paint · ${new Set(strokes.map((s) => s.colour)).size} colour(s)`,
      });
      const job = await trackJob("Painting", accepted.job_id);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string })?.message ?? "the paint did not land");
        return;
      }
      setStrokes([]);
      setPaintMode(false);
      await refresh();
      await showResult(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function exportModel(format: "stl" | "3mf" | "glb" | "step" | "iges") {
    if (!client || !activeVersion) return;
    setError(null);
    const printable = format === "stl" || format === "3mf";
    let accepted;
    try {
      accepted = await client.exportModel(activeVersion.id, { format, printable });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return;
    }
    const job = await trackJob(`Exporting ${format.toUpperCase()}`, accepted.job_id);
    if (job.status !== "succeeded") {
      setError((job.error as { message?: string })?.message ?? "export failed");
      return;
    }
    const result = job.result as { asset_id: string };
    const download = await client.download(result.asset_id);
    setDownloads((d) => [{ format, url: download.url }, ...d]);
  }

  if (!ready) return null;
  if (!session) return <div className="card">Sign in to open projects.</div>;

  const report = analysis?.report as
    | {
        score?: { total: number; status: string; subscores: { name: string; score: number; reason: string }[] };
        warnings?: { code: string; severity: string; message: string }[];
        summary?: string;
        metrics?: { mass_g?: number | null; print_time_min?: number | null; total_cost?: number | null; currency?: string };
        recommended?: { orientation: { label: string } } | null;
      }
    | undefined;

  const ru = language === "ru";
  const tools: { id: Tool; label: string; glyph: string; hint: string; advanced?: boolean }[] = [
    { id: "chat", label: ru ? "Чат ИИ" : "AI chat", glyph: "✦", hint: ru ? "Опишите, что построить или изменить" : "Describe what to build or change" },
    { id: "shape", label: ru ? "Форма" : "Shape", glyph: "⬡", hint: ru ? "Коробка или цилиндр: создать, добавить, вычесть" : "Box or cylinder: create, add, subtract" },
    { id: "detail", label: ru ? "Деталь" : "Detail", glyph: "◉", hint: ru ? "Отверстие, скругление или фаска" : "Hole, fillet or chamfer" },
    { id: "photo", label: ru ? "Фото" : "Photo", glyph: "◫", hint: ru ? "Модель по фотографии" : "A model from a photo" },
    { id: "region", label: ru ? "Область" : "Region", glyph: "◌", hint: ru ? "Выделите область и скажите, что там должно быть" : "Outline an area and say what belongs there" },
    { id: "paint", label: ru ? "Кисть" : "Paint", glyph: "✎", hint: ru ? "Покрасить участки" : "Paint parts of the model" },
    { id: "size", label: ru ? "Размеры" : "Size", glyph: "⤢", hint: ru ? "Точные габариты" : "Exact dimensions" },
    { id: "reverse", label: ru ? "В CAD" : "To CAD", glyph: "◇", hint: ru ? "Распознать геометрию и сделать редактируемой" : "Recognize geometry and make it editable" },
    { id: "engineer", label: ru ? "Инженер" : "Engineer", glyph: "⚙", hint: ru ? "Спросить инженера, материал, облегчить" : "Ask the engineer, material, lighten" },
    { id: "fit", label: ru ? "Посадка" : "Fit", glyph: "⧉", hint: ru ? "Проверить посадку с другой деталью" : "Fit test against another part" },
    { id: "parts", label: ru ? "Части" : "Parts", glyph: "✂", hint: ru ? "Нарезать на части, другие тела" : "Cut into parts, other bodies" },
    { id: "print", label: ru ? "Печать" : "Print", glyph: "▤", hint: ru ? "Проверка печати и ориентация" : "Print check and orientation" },
    { id: "export", label: ru ? "Экспорт" : "Export", glyph: "⇪", hint: "STL · 3MF · GLB · STEP · IGES" },
    { id: "versions", label: ru ? "Версии" : "Versions", glyph: "⟲", hint: ru ? "История версий и откат" : "Version history and rollback" },
    { id: "history", label: ru ? "Команды" : "Commands", glyph: "☰", hint: ru ? "История команд ИИ" : "AI command history", advanced: true },
    { id: "origin", label: ru ? "Источник" : "Origin", glyph: "⌥", hint: ru ? "Откуда взялась модель" : "Where the model came from", advanced: true },
    { id: "licence", label: ru ? "Лицензия" : "Licence", glyph: "§", hint: ru ? "Лицензия, источник, ремикс" : "Licence, source, remix", advanced: true },
    { id: "market", label: ru ? "Маркет" : "Market", glyph: "◈", hint: ru ? "Выставить на маркетплейс" : "Put it on the marketplace", advanced: true },
  ];
  const visibleTools = tools.filter((item) => studioMode === "pro" || showAllTools || !item.advanced);
  const panelTitle = tools.find((t) => t.id === tool)?.label ?? "";

  return (
    <div className="studio" data-tool={tool ?? "none"} style={{ top: topOffset }}>
      <div className="studio-stage">
          <ModelViewer
            url={modelUrl}
            format={modelFormat}
            bodyId={activeVersion ? bodyOf(activeVersion) : "body"}
            selected={selected}
            onSelect={setSelected}
            onMeasure={setSize}
            regionMode={regionMode || paintMode}
            paintColour={paintMode ? colour : null}
            brushMm={brush}
            cutPlanes={cutPlanes}
            displayMode={displayMode}
            showGrid={showGrid}
            onRegion={(next) => {
              if (!paintMode) {
                setRegion(next);
                return;
              }
              if (next) setStrokes((all) => [...all, { colour, region: next }]);
            }}
          />
      </div>

      <div className="studio-top">
        <strong className="studio-name">{project?.name ?? "…"}</strong>
        {activeVersion && (
          <span className="chip">
            v{activeVersion.sequence_no} · {activeVersion.label ?? (ru ? "без названия" : "untitled")}
          </span>
        )}
        <span className="muted">
          {versions.length} {ru ? "верс." : versions.length === 1 ? "version" : "versions"}
        </span>
        {busy && (
          <span className="chip studio-busy">
            {busy.label}
            {busy.job ? ` · ${busy.job.progress}%` : "…"}
          </span>
        )}
        <span className="spacer" />
        <div className="studio-mode" aria-label={ru ? "Режим редактора" : "Editor mode"}>
          <button
            type="button"
            className={studioMode === "simple" ? "active" : ""}
            onClick={() => {
              setStudioMode("simple");
              setShowAllTools(false);
              setDisplayMode("solid");
              setShowGrid(true);
              setTool((current) =>
                current && (["history", "origin", "licence", "market"] as Tool[]).includes(current)
                  ? null
                  : current,
              );
            }}
          >
            {ru ? "Простой" : "Simple"}
          </button>
          <button
            type="button"
            className={studioMode === "pro" ? "active" : ""}
            onClick={() => {
              setStudioMode("pro");
              setShowAllTools(true);
            }}
          >
            Pro
          </button>
        </div>
        {studioMode === "pro" && (
          <div className="studio-view-controls" aria-label={ru ? "Отображение модели" : "Model display"}>
            {(["solid", "wire", "xray"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                className={displayMode === mode ? "active" : ""}
                onClick={() => setDisplayMode(mode)}
              >
                {mode === "solid" ? (ru ? "Объём" : "Solid") : mode === "wire" ? (ru ? "Сетка" : "Wire") : "X-ray"}
              </button>
            ))}
            <button type="button" className={showGrid ? "active" : ""} onClick={() => setShowGrid((value) => !value)}>
              {ru ? "Пол" : "Grid"}
            </button>
          </div>
        )}
      </div>

      <nav className="studio-rail" aria-label={ru ? "Инструменты" : "Tools"}>
        {visibleTools.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`tool-btn ${tool === item.id ? "active" : ""}`}
            title={item.hint}
            aria-pressed={tool === item.id}
            onClick={() => {
              if (item.id === "photo") {
                setTool("chat");
                photoInput.current?.click();
                return;
              }
              if (item.id === "region") {
                setTool("chat");
                setPaintMode(false);
                setRegionMode((on) => !on);
                setRegion(null);
                return;
              }
              if (item.id === "paint") {
                setRegionMode(false);
                setRegion(null);
                setPaintMode((on) => (tool === "paint" ? !on : true));
              }
              setTool((current) => (current === item.id ? null : item.id));
            }}
          >
            <span className="tool-glyph" aria-hidden="true">{item.glyph}</span>
            <span className="tool-label">{item.label}</span>
          </button>
        ))}
        {studioMode === "simple" && (
          <button
            type="button"
            className={`tool-btn tool-more ${showAllTools ? "active" : ""}`}
            title={ru ? "История, источник, лицензия и маркетплейс" : "History, origin, licence and marketplace"}
            aria-expanded={showAllTools}
            onClick={() =>
              setShowAllTools((value) => {
                const next = !value;
                if (!next) {
                  setTool((current) =>
                    current && (["history", "origin", "licence", "market"] as Tool[]).includes(current)
                      ? null
                      : current,
                  );
                }
                return next;
              })
            }
          >
            <span className="tool-glyph" aria-hidden="true">•••</span>
            <span className="tool-label">{ru ? "Ещё" : "More"}</span>
          </button>
        )}
      </nav>

      {tool && (
        <aside className="studio-panel">
          <div className="studio-panel-head">
            <strong>{panelTitle}</strong>
            <span className="spacer" />
            <button type="button" className="btn" onClick={() => setTool(null)} aria-label={ru ? "Закрыть" : "Close"}>
              ✕
            </button>
          </div>
          <div className="studio-panel-body">
            {tool === "chat" && (
          <form className="stack" onSubmit={sendCommand}>
            <strong>{language === "ru" ? "Чат с ИИ: опишите, что нужно" : "Describe what you want"}</strong>
            {regionMode && (
              <span className="muted">
                Draw around the area, then say what belongs there — “a 6 mm hole”, “a pocket
                3 mm deep”, “raise this 2 mm”.
              </span>
            )}
            {nextSteps.length > 0 && versions.length > 0 && (
              <div className="row" style={{ flexWrap: "wrap" }}>
                <span className="muted">Try next:</span>
                {nextSteps.map((step) => (
                  <span key={step} className="chip">
                    {step}
                  </span>
                ))}
              </div>
            )}
            {versions.length === 0 && (
              <div className="row">
                <span className="muted">Try:</span>
                {EXAMPLES.map((example) => (
                  <button
                    key={example}
                    type="button"
                    className="chip"
                    onClick={() => setPrompt(example)}
                  >
                    {example}
                  </button>
                ))}
              </div>
            )}
            <textarea
              ref={promptBox}
              className="textarea"
              placeholder="Органайзер 200×100×50 мм с 6 секциями, скругление 1.5 мм"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
            <div className="row">
              <VoiceButton
                language={language}
                disabled={!!busy}
                onText={setPrompt}
                onFinal={(text) => {
                  setPrompt(text);
                  if (handsFree) void sendCommand(null, text);
                }}
              />
              <label className="muted" style={{ fontSize: 12 }}>
                <input
                  type="checkbox"
                  checked={handsFree}
                  onChange={(event) => setHandsFree(event.target.checked)}
                />{" "}
                hands-free: build when I stop talking
              </label>
            </div>
            <div className="row" style={{ flexWrap: "wrap" }}>
              <input
                ref={photoInput}
                type="file"
                accept="image/jpeg,image/png"
                capture="environment"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) void attachPhoto(file);
                }}
              />
              <button
                type="button"
                className={`btn ${photo ? "primary" : ""}`}
                disabled={!!busy}
                onClick={() => photoInput.current?.click()}
                title="Photograph the object; the AI rebuilds it as an editable, printable part"
              >
                {photo ? "Photo attached" : "From a photo"}
              </button>
              {photo && (
                <>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={photo.url}
                    alt="the attached photo"
                    style={{ height: 44, borderRadius: 6, border: "1px solid #ccc" }}
                  />
                  <input
                    className="input"
                    style={{ maxWidth: 260 }}
                    placeholder="known size in the photo: “credit card”, “width 80 mm”"
                    value={reference}
                    onChange={(event) => setReference(event.target.value)}
                  />
                  <button className="btn" type="button" onClick={dropPhoto}>
                    remove
                  </button>
                </>
              )}
              <button
                type="button"
                className={`btn ${regionMode ? "primary" : ""}`}
                disabled={!modelUrl}
                onClick={() => {
                  setRegionMode((on) => !on);
                  setRegion(null);
                }}
                title="Draw around a part of the model, then say what belongs there"
              >
                {regionMode ? "Outlining…" : "Outline an area"}
              </button>
              {region && (
                <span className="chip mono" title="the volume your outline sweeps">
                  region {regionSize(region)}
                </span>
              )}
              {region && (
                <button className="btn" type="button" onClick={() => setRegion(null)}>
                  clear
                </button>
              )}
            </div>
            <div className="row">
              <button
                className="btn primary"
                type="submit"
                disabled={!!busy || (!prompt.trim() && !photo)}
              >
                {language === "ru" ? "Построить" : "Build"}
              </button>
              <button
                className="btn"
                type="button"
                disabled={!!busy || !prompt.trim()}
                onClick={() => void buildVariants()}
                title={
                  language === "ru"
                    ? "Тот же запрос тремя способами — оставьте тот, что нравится"
                    : "The same request answered three ways; keep the one you like"
                }
              >
                {language === "ru" ? "3 эскиза" : "3 sketches"}
              </button>
              <label className="row muted" style={{ gap: 6 }}>
                <input
                  type="checkbox"
                  checked={previewMode}
                  onChange={(e) => setPreviewMode(e.target.checked)}
                />
                preview first
              </label>
              {selected.length > 0 && (
                <span className="muted">scope: {selected.join(", ")}</span>
              )}
              {busy && (
                <span className="muted">
                  {busy.label}
                  {busy.job ? ` · ${busy.job.progress}% ${busy.job.stage ?? ""}` : "…"}
                </span>
              )}
            </div>
            {busy?.job && (
              <div className="progress">
                <div style={{ width: `${busy.job.progress}%` }} />
              </div>
            )}
            {pending && (
              <div className="stack">
                <div className="status-yellow">
                  {pending.clarifications.map((q) => (
                    <div key={q}>{q}</div>
                  ))}
                </div>
                <div className="row">
                  <input
                    className="input"
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void sendAnswer(e);
                    }}
                    placeholder="Your answer"
                  />
                  <button
                    className="btn"
                    type="button"
                    disabled={!answer.trim() || !!busy}
                    onClick={() => void sendAnswer()}
                  >
                    Answer
                  </button>
                </div>
              </div>
            )}
            {error && <div className="error">{error}</div>}
            {notice && <div className="muted">{notice}</div>}
          </form>
            )}
            {tool === "shape" && (
              <div className="stack">
                <strong>{activeVersion ? (ru ? "Добавить или вычесть форму" : "Add or subtract a shape") : (ru ? "Начать модель с формы" : "Start with a shape")}</strong>
                <div className="segmented">
                  <button type="button" className={primitiveKind === "box" ? "active" : ""} onClick={() => setPrimitiveKind("box")}>{ru ? "Коробка" : "Box"}</button>
                  <button type="button" className={primitiveKind === "cylinder" ? "active" : ""} onClick={() => setPrimitiveKind("cylinder")}>{ru ? "Цилиндр" : "Cylinder"}</button>
                </div>
                {activeVersion && (
                  <div className="segmented">
                    <button type="button" className={primitiveMode === "add" ? "active" : ""} onClick={() => setPrimitiveMode("add")}>＋ {ru ? "Добавить" : "Add"}</button>
                    <button type="button" className={primitiveMode === "cut" ? "active" : ""} onClick={() => setPrimitiveMode("cut")}>− {ru ? "Вычесть" : "Subtract"}</button>
                  </div>
                )}
                <div className="primitive-grid">
                  {primitiveKind === "box" ? (
                    <>
                      <label>{ru ? "Ширина X" : "Width X"}<input className="input mono" type="number" min="0.1" value={primitiveSize.width} onChange={(event) => setPrimitiveSize((value) => ({ ...value, width: Number(event.target.value) }))} /></label>
                      <label>{ru ? "Глубина Y" : "Depth Y"}<input className="input mono" type="number" min="0.1" value={primitiveSize.depth} onChange={(event) => setPrimitiveSize((value) => ({ ...value, depth: Number(event.target.value) }))} /></label>
                    </>
                  ) : (
                    <label>{ru ? "Диаметр" : "Diameter"}<input className="input mono" type="number" min="0.1" value={primitiveSize.diameter} onChange={(event) => setPrimitiveSize((value) => ({ ...value, diameter: Number(event.target.value) }))} /></label>
                  )}
                  <label>{ru ? "Высота Z" : "Height Z"}<input className="input mono" type="number" min="0.1" value={primitiveSize.height} onChange={(event) => setPrimitiveSize((value) => ({ ...value, height: Number(event.target.value) }))} /></label>
                </div>
                {activeVersion && (
                  <>
                    <span className="muted">{ru ? "Положение начала формы, мм" : "Shape origin, mm"}</span>
                    <div className="primitive-grid three">
                      {(["x", "y", "z"] as const).map((axis) => (
                        <label key={axis}>{axis.toUpperCase()}<input className="input mono" type="number" value={primitiveOrigin[axis]} onChange={(event) => setPrimitiveOrigin((value) => ({ ...value, [axis]: Number(event.target.value) }))} /></label>
                      ))}
                    </div>
                  </>
                )}
                <button className="btn primary" type="button" disabled={!!busy} onClick={() => void applyPrimitive()}>
                  {!activeVersion ? (ru ? "Создать форму" : "Create shape") : primitiveMode === "add" ? (ru ? "Добавить к модели" : "Add to model") : (ru ? "Вырезать из модели" : "Subtract from model")}
                </button>
                <span className="muted">
                  {ru ? "Каждая операция создаёт новую версию. Для импортированного mesh сначала используйте «В CAD»." : "Every operation creates a new version. Use To CAD first for an imported mesh."}
                </span>
              </div>
            )}
            {tool === "detail" && (
              <div className="stack">
                <strong>{ru ? "Точные операции с деталью" : "Exact detail operations"}</strong>
                {!activeVersion ? (
                  <span className="muted">{ru ? "Сначала создайте форму или модель." : "Create a shape or model first."}</span>
                ) : (
                  <>
                    <div className="segmented">
                      <button type="button" className={detailKind === "hole" ? "active" : ""} onClick={() => setDetailKind("hole")}>{ru ? "Отверстие" : "Hole"}</button>
                      <button type="button" className={detailKind === "fillet" ? "active" : ""} onClick={() => setDetailKind("fillet")}>{ru ? "Скругление" : "Fillet"}</button>
                      <button type="button" className={detailKind === "chamfer" ? "active" : ""} onClick={() => setDetailKind("chamfer")}>{ru ? "Фаска" : "Chamfer"}</button>
                    </div>
                    {detailKind === "hole" ? (
                      <>
                        <div className="row">
                          <span className="muted">{ru ? "Грань" : "Face"}</span>
                          <div className="segmented" style={{ flex: 1 }}>
                            {(["x", "y", "z"] as const).map((axis) => (
                              <button key={axis} type="button" className={holeAxis === axis ? "active" : ""} onClick={() => setHoleAxis(axis)}>{axis.toUpperCase()}</button>
                            ))}
                          </div>
                          <div className="segmented">
                            {(["+", "-"] as const).map((side) => (
                              <button key={side} type="button" className={holeSide === side ? "active" : ""} onClick={() => setHoleSide(side)}>{side}</button>
                            ))}
                          </div>
                        </div>
                        <div className="primitive-grid">
                          <label>{ru ? "Позиция U" : "Position U"}<input className="input mono" type="number" value={holePosition.u} onChange={(event) => setHolePosition((value) => ({ ...value, u: Number(event.target.value) }))} /></label>
                          <label>{ru ? "Позиция V" : "Position V"}<input className="input mono" type="number" value={holePosition.v} onChange={(event) => setHolePosition((value) => ({ ...value, v: Number(event.target.value) }))} /></label>
                          <label>{ru ? "Диаметр, мм" : "Diameter, mm"}<input className="input mono" type="number" min="0.1" value={holeDiameter} onChange={(event) => setHoleDiameter(Number(event.target.value))} /></label>
                          {!holeThrough && <label>{ru ? "Глубина, мм" : "Depth, mm"}<input className="input mono" type="number" min="0.1" value={holeDepth} onChange={(event) => setHoleDepth(Number(event.target.value))} /></label>}
                        </div>
                        <label className="row muted"><input type="checkbox" checked={holeThrough} onChange={(event) => setHoleThrough(event.target.checked)} />{ru ? "Сквозное отверстие" : "Through hole"}</label>
                      </>
                    ) : (
                      <label className="stack" style={{ gap: 6 }}>
                        <span>{detailKind === "fillet" ? (ru ? "Радиус, мм" : "Radius, mm") : (ru ? "Размер фаски, мм" : "Chamfer size, mm")}</span>
                        <input className="input mono" type="number" min="0.1" value={edgeSize} onChange={(event) => setEdgeSize(Number(event.target.value))} />
                        <span className="muted">{ru ? "Операция применяется ко всем рёбрам. Выбор отдельных рёбер появится в следующем расширении Pro." : "Applied to all edges. Individual edge selection follows in the Pro extension."}</span>
                      </label>
                    )}
                    <button className="btn primary" type="button" disabled={!!busy} onClick={() => void applyDetail()}>
                      {detailKind === "hole" ? (ru ? "Добавить отверстие" : "Add hole") : detailKind === "fillet" ? (ru ? "Скруглить рёбра" : "Round edges") : (ru ? "Добавить фаску" : "Add chamfer")}
                    </button>
                  </>
                )}
              </div>
            )}
            {tool === "paint" && (
          <div className="stack">
            <div className="row">
              <strong>{ru ? "Кисть" : "Paint"}</strong>
              <span className="spacer" />
              <button
                type="button"
                className={`btn ${paintMode ? "primary" : ""}`}
                disabled={!modelUrl}
                onClick={() => {
                  setPaintMode((on) => !on);
                  setRegionMode(false);
                  setRegion(null);
                }}
              >
                {paintMode ? "Painting…" : "Paint"}
              </button>
            </div>
            {paintMode && (
              <>
                <div className="row">
                  {PALETTE.map((swatch) => (
                    <button
                      key={swatch}
                      type="button"
                      aria-label={swatch}
                      className={`swatch ${colour === swatch ? "selected" : ""}`}
                      style={{ background: swatch }}
                      onClick={() => setColour(swatch)}
                    />
                  ))}
                  <input
                    type="color"
                    className="swatch"
                    value={colour}
                    onChange={(event) => setColour(event.target.value)}
                  />
                </div>
                <div className="row">
                  <span className="muted">Brush</span>
                  {BRUSHES.map((option) => (
                    <button
                      key={option.mm}
                      type="button"
                      className={`btn ${brush === option.mm ? "primary" : ""}`}
                      onClick={() => setBrush(option.mm)}
                    >
                      {option.label} · {option.mm} mm
                    </button>
                  ))}
                </div>
                <span className="muted">
                  Sweep to paint a band, close a loop to fill it. The shape never changes —
                  the paint is a new version on top of what is already there.
                </span>
                <div className="row">
                  <span className="muted">
                    {strokes.length} stroke{strokes.length === 1 ? "" : "s"}
                  </span>
                  <button
                    className="btn primary"
                    type="button"
                    disabled={!strokes.length || !!busy}
                    onClick={applyPaint}
                  >
                    Keep the paint
                  </button>
                  <button
                    className="btn"
                    type="button"
                    disabled={!strokes.length || !!busy}
                    onClick={() => setStrokes([])}
                  >
                    Start over
                  </button>
                </div>
              </>
            )}
          </div>


            )}
            {tool === "size" && (
          <Inspector
            size={size}
            target={activeVersion ? bodyOf(activeVersion) : null}
            disabled={!activeVersion || !!busy}
            onApply={applyDimensions}
          />


            )}
            {tool === "reverse" && (
              <div className="stack">
                <strong>{ru ? "Mesh → параметрическая CAD-модель" : "Mesh → parametric CAD"}</strong>
                <span className="muted">
                  {ru
                    ? "Система распознаёт плоскости, профили, цилиндры, отверстия, фаски, резьбы, симметрию и повторы. Затем CAD-ядро строит новую редактируемую версию и измеряет отклонение от исходника."
                    : "The system recognizes planes, profiles, cylinders, holes, edge treatments, threads, symmetry and patterns. The CAD kernel then builds an editable version and measures it against the source."}
                </span>
                <label className="stack" style={{ gap: 6 }}>
                  <span>{ru ? "Допуск распознавания, мм" : "Recognition tolerance, mm"}</span>
                  <input
                    className="input mono"
                    type="number"
                    min="0.02"
                    max="5"
                    step="0.05"
                    value={reconstructionTolerance}
                    onChange={(event) => setReconstructionTolerance(Number(event.target.value))}
                  />
                </label>
                <button
                  className="btn primary"
                  type="button"
                  disabled={!activeVersion || !!busy || !Number.isFinite(reconstructionTolerance)}
                  onClick={() => void reconstructCad()}
                >
                  {ru ? "Сделать редактируемой" : "Make editable"}
                </button>
                {reconstruction && (
                  <div className="reconstruction-report stack">
                    <div className="row">
                      <span className="chip">{reconstruction.features.reconstruction?.fidelity ?? "CAD"}</span>
                      <span className="chip">{reconstruction.features.cylinders.length} {ru ? "цилиндров" : "cylinders"}</span>
                      <span className="chip">{reconstruction.features.planes.length} {ru ? "плоскостей" : "planes"}</span>
                    </div>
                    <strong>
                      {ru ? "Точность новой модели" : "Rebuild accuracy"}: p95 {reconstruction.deviation.p95_mm.toFixed(3)} mm
                    </strong>
                    <span className="muted">
                      {ru ? "Среднее" : "Mean"} {reconstruction.deviation.mean_mm.toFixed(3)} mm · max {reconstruction.deviation.max_mm.toFixed(3)} mm · {Math.round(reconstruction.deviation.within_tolerance * 100)}% {ru ? "в допуске" : "within tolerance"}
                    </span>
                    <div className="progress" title={`${Math.round(reconstruction.deviation.within_tolerance * 100)}%`}>
                      <div style={{ width: `${reconstruction.deviation.within_tolerance * 100}%` }} />
                    </div>
                    {reconstruction.features.warnings.map((warning) => (
                      <span key={warning} className="status-yellow">{warning}</span>
                    ))}
                  </div>
                )}
              </div>
            )}
            {tool === "engineer" && (
          <EngineerCard
            disabled={!activeVersion || !!busy}
            hasRegion={region !== null}
            onAsk={askEngineer}
            onApplyFix={applyFix}
            onAdapt={adaptMaterial}
            onLighten={lighten}
          />


            )}
            {tool === "fit" && (
          <FitTestCard
            projects={others}
            currentProjectId={projectId}
            disabled={!activeVersion || !!busy}
            onRun={runFitTest}
            onApplyFix={applyFix}
          />


            )}
            {tool === "parts" && (
              <div className="stack">
          <PartsCard version={activeVersion} disabled={!!busy} onDownload={downloadPart} />


          <SplitCard
            version={activeVersion}
            size={size ? { x: size.x, y: size.y, z: size.z } : null}
            disabled={!activeVersion || !modelUrl || !!busy}
            hasPrinter={printers.length > 0}
            onPreview={setCutPlanes}
            onCut={cutIntoParts}
            onDownload={downloadPart}
          />


              </div>
            )}
            {tool === "print" && (
          <div className="stack">
            <strong>{ru ? "Проверка печати" : "Print check"}</strong>
            {report?.score ? (
              <>
                <div className={`score ${statusClass(report.score.status)}`}>
                  {Math.round(report.score.total)}
                  <span className="muted" style={{ fontSize: 14 }}>
                    {" "}
                    / 100 · {report.score.status}
                  </span>
                </div>
                <div className="muted">{report.summary}</div>
                <ul className="list">
                  {report.score.subscores.map((s) => (
                    <li key={s.name}>
                      <strong>{s.name}</strong> {Math.round(s.score)} — <span className="muted">{s.reason}</span>
                    </li>
                  ))}
                  {report.warnings?.map((w) => (
                    <li key={w.code} className={statusClass(w.severity === "error" ? "red" : "yellow")}>
                      {w.message}
                    </li>
                  ))}
                </ul>
                {report.metrics && (
                  <div className="muted">
                    {report.metrics.mass_g != null && `${report.metrics.mass_g.toFixed(0)} g`}
                    {report.metrics.print_time_min != null && ` · ~${Math.round(report.metrics.print_time_min)} min`}
                    {report.metrics.total_cost != null && ` · ${report.metrics.total_cost.toFixed(2)} ${report.metrics.currency ?? ""}`}
                  </div>
                )}
                {report.recommended && (
                  <div className="muted">Best orientation: {report.recommended.orientation.label}</div>
                )}
              </>
            ) : (
              <div className="muted">No analysis yet.</div>
            )}
            <div className="row">
              <button className="btn" onClick={analyze} disabled={!activeVersion || !!busy}>
                Analyze
              </button>
              <button className="btn" onClick={() => optimize(false)} disabled={!activeVersion || !!busy}>
                Best orientation
              </button>
              <button className="btn" onClick={() => optimize(true)} disabled={!activeVersion || !!busy}>
                Apply
              </button>
            </div>
          </div>


            )}
            {tool === "export" && (
          <div className="stack">
            <strong>{ru ? "Экспорт" : "Export"}</strong>
            <div className="row" style={{ flexWrap: "wrap" }}>
              {(["stl", "3mf", "glb", "step", "iges"] as const).map((format) => (
                <button
                  key={format}
                  className="btn"
                  onClick={() => exportModel(format)}
                  disabled={!activeVersion || !!busy}
                  title={
                    format === "step" || format === "iges"
                      ? "CAD-ready: the exact B-Rep, for Fusion, SolidWorks, FreeCAD (F-078)"
                      : undefined
                  }
                >
                  {format.toUpperCase()}
                </button>
              ))}
            </div>
            <span className="muted" style={{ fontSize: 12 }}>
              STL/3MF for printing, GLB for engines, STEP/IGES for CAD (versions with a B-Rep).
            </span>
            {downloads.map((d) => (
              <a key={d.url} href={d.url} className="mono">
                download {d.format}
              </a>
            ))}
          </div>


            )}
            {tool === "origin" && (
              <>
          {graph && (
            <div className="stack">
              <div className="row">
                <strong>{ru ? "Откуда это" : "Where it came from"}</strong>
                <span className="muted">
                  {graph.summary.versions as number} version(s)
                  {graph.summary.credits && (graph.summary.credits as string[]).length > 0
                    ? ` · credits: ${(graph.summary.credits as string[]).join("; ")}`
                    : ""}
                </span>
                <span className="spacer" />
                <button className="btn" type="button" onClick={() => setShowGraph((on) => !on)}>
                  {showGraph ? "Hide the graph" : "Show the graph"}
                </button>
              </div>
              {showGraph && (
                <ProvenanceGraph
                  graph={graph}
                  activeVersionId={activeVersion?.id ?? null}
                  onSelect={(versionId) => {
                    const found = versions.find((v) => v.id === versionId);
                    if (found) setActiveVersion(found);
                  }}
                />
              )}
            </div>
          )}


                {!graph && <span className="muted">{ru ? "Пока нечего показать." : "Nothing to show yet."}</span>}
              </>
            )}
            {tool === "versions" && (
          <div className="stack">
            <div className="row">
              <strong>{ru ? "Версии" : "Versions"}</strong>
              <span className="spacer" />
              {activeVersion && project?.head_version && activeVersion.id !== project.head_version.id && (
                <button
                  type="button"
                  className="btn"
                  disabled={!!busy}
                  onClick={() => void restoreVersion(activeVersion)}
                  title="Make this the current version — as a new version, nothing is deleted"
                >
                  Make v{activeVersion.sequence_no} current
                </button>
              )}
            </div>
            <span className="muted">
              Or type it: «верни как было два часа назад», «go back to v2», «undo».
            </span>
            <ul className="list">
              {versions.map((v) => (
                <li
                  key={v.id}
                  className={v.id === activeVersion?.id ? "active" : ""}
                  onClick={() => setActiveVersion(v)}
                  style={{ cursor: "pointer" }}
                >
                  v{v.sequence_no} · {v.label ?? "untitled"}{" "}
                  <span className="muted">{new Date(v.created_at).toLocaleString()}</span>
                </li>
              ))}
            </ul>
          </div>


            )}
            {tool === "licence" && (
              <>
          {project && (
            <LicenceCard
              project={project}
              licences={licences}
              terms={terms}
              disabled={!!busy}
              onSave={saveLicense}
              onRemix={remix}
            />
          )}
              </>
            )}
            {tool === "market" && (
              <>
          {project && project.head_version_id && (
            <PublishCard
              project={project}
              licences={licences}
              listings={listings}
              disabled={!!busy}
              onPublish={publishListing}
              onWithdraw={withdrawListing}
            />
          )}


                {!(project && project.head_version_id) && (
                  <span className="muted">{ru ? "Сначала постройте модель." : "Build a model first."}</span>
                )}
              </>
            )}
            {tool === "history" && (
          <div className="stack">
            <strong>{ru ? "История ИИ" : "AI history"}</strong>
            <ul className="list">
              {history.map((h) => (
                <li key={h.id}>
                  <div>
                    {h.photo_asset_ids?.length ? "📷 " : ""}
                    {h.prompt}
                  </div>
                  <div className={`muted ${h.status === "executed" ? "status-green" : ""}`}>
                    {h.status}
                    {h.result_version_id && " · version created"}
                  </div>
                </li>
              ))}
              {history.length === 0 && <li className="muted">No commands yet.</li>}
            </ul>
          </div>

            )}
          </div>
        </aside>
      )}

      <div className="studio-overlays">
      {variants.length > 0 && (
        <div className="card stack" style={{ borderColor: "var(--yellow)" }}>
          <strong>
            {language === "ru"
              ? `Эскизы: ${variants.length} варианта — выберите один`
              : `${variants.length} sketches — pick one`}
          </strong>
          <span className="muted">{sketchPrompt}</span>
          <div className="row" style={{ flexWrap: "wrap" }}>
            {variants.map((variant) => (
              <div
                key={variant.version.id}
                className="card stack"
                style={{
                  cursor: "pointer",
                  borderColor:
                    activeVersion?.id === variant.version.id ? "var(--accent)" : undefined,
                }}
                onClick={() => setActiveVersion(variant.version)}
              >
                <strong>{variant.title}</strong>
                <span className="muted mono">
                  {variant.size ? variant.size.map((v) => v.toFixed(1)).join(" × ") + " mm" : "—"}
                </span>
                <button
                  type="button"
                  className="btn primary"
                  disabled={!!busy}
                  onClick={(event) => {
                    event.stopPropagation();
                    void chooseVariant(variant.version);
                  }}
                >
                  {language === "ru" ? "Оставить этот" : "Keep this one"}
                </button>
              </div>
            ))}
          </div>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <button
              type="button"
              className="btn"
              disabled={!!busy}
              onClick={() => void buildVariants(sketchPrompt)}
              title={
                language === "ru"
                  ? "Тот же запрос — три новых ответа"
                  : "The same request, three new answers"
              }
            >
              {language === "ru" ? "Посмотреть другие" : "See others"}
            </button>
            <button
              type="button"
              className="btn"
              disabled={!!busy}
              onClick={() => {
                setPrompt(sketchPrompt);
                promptBox.current?.focus();
              }}
            >
              {language === "ru" ? "Уточнить запрос" : "Refine the request"}
            </button>
            <span className="muted">
              {language === "ru"
                ? "Кликните карточку, чтобы увидеть эскиз в окне; остальные удалятся, когда вы оставите один."
                : "Click a card to see it in the viewport; the others are discarded when you keep one."}
            </span>
          </div>
        </div>
      )}


      {preview && (
        <div className="card stack" style={{ borderColor: "var(--yellow)" }}>
          <strong>Preview — not kept yet</strong>
          <div className="row">
            {(["before", "after"] as const).map((side) => {
              const state = preview.diff[side];
              if (!state) return null;
              return (
                <div key={side} className="chip mono">
                  {side}: {state.size_mm ? state.size_mm.map((v) => v.toFixed(1)).join(" × ") : "—"}{" "}
                  mm
                  {state.volume_mm3 != null && ` · ${Math.round(state.volume_mm3)} mm³`}
                </div>
              );
            })}
            {typeof preview.diff.changed.volume_delta_pct === "number" && (
              <span className="muted">
                volume {preview.diff.changed.volume_delta_pct > 0 ? "+" : ""}
                {preview.diff.changed.volume_delta_pct}%
              </span>
            )}
          </div>
          <div className="row">
            <button className="btn primary" onClick={() => decidePreview(true)} disabled={!!busy}>
              Keep it
            </button>
            <button className="btn" onClick={() => decidePreview(false)} disabled={!!busy}>
              Discard
            </button>
          </div>
        </div>
      )}


      </div>

      {tool !== "chat" && (
        <form
          className="studio-dock"
          onSubmit={(event) => {
            event.preventDefault();
            void sendCommand(null, prompt);
          }}
        >
          <input
            className="input"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder={ru ? "Скажите ИИ, что построить или изменить…" : "Tell the AI what to build or change…"}
            disabled={!!busy}
          />
          <button className="btn primary" type="submit" disabled={!!busy || (!prompt.trim() && !photo)}>
            {ru ? "Построить" : "Build"}
          </button>
          <button className="btn" type="button" disabled={!!busy || !prompt.trim()} onClick={() => void buildVariants()}>
            {ru ? "3 эскиза" : "3 sketches"}
          </button>
          {(error || notice || pending) && (
            <button type="button" className="btn" onClick={() => setTool("chat")}>
              {pending ? (ru ? "Ответить ИИ" : "Answer the AI") : error ? (ru ? "Ошибка ↗" : "Error ↗") : "…"}
            </button>
          )}
        </form>
      )}
    </div>
  );
}
