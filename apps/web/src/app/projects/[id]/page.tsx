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

/** First-run prompts (T-098): a new project is a blank page until it suggests something. */
const EXAMPLES = [
  "Органайзер 200×100×50 мм с 6 секциями, скругление 1.5 мм",
  "Bracket 60x40x8 mm with 2 holes 5 mm",
  "Cylinder diameter 40 mm, height 20 mm",
];

/** The kernel body name the version's model was built from; edits target it by id (T-049). */
function bodyOf(version: Version): string {
  const bodies = (version.provenance as { bodies?: { name?: string }[] } | null)?.bodies ?? [];
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
  const [selected, setSelected] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
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
    const head = summary.head_version ?? null;
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
    void client.download(shownAssetId).then((d) => !cancelled && setModelUrl(d.url));
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
  async function buildVariants() {
    if (!client || !prompt.trim()) return;
    setError(null);
    setVariants([]);
    try {
      const accepted = await client.createVariants(projectId, {
        prompt: prompt.trim(),
        count: 3,
        project_version_id: activeVersion?.id ?? null,
        selection_entity_ids: selected,
        region,
        target: "print",
      });
      setBusy({ label: "Building 3 variants" });
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
      setDownloads((d) => [{ format: `${name}.stl`, url: download.url }, ...d]);
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

  return (
    <div className="stack">
      <div className="row">
        <h2 style={{ margin: 0 }}>{project?.name ?? "…"}</h2>
        <span className="muted">
          {versions.length} version{versions.length === 1 ? "" : "s"}
        </span>
        {activeVersion && (
          <span className="chip">
            v{activeVersion.sequence_no} · {activeVersion.label ?? "untitled"}
          </span>
        )}
      </div>

      {variants.length > 0 && (
        <div className="card stack" style={{ borderColor: "var(--yellow)" }}>
          <strong>{variants.length} variants — pick one</strong>
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
                  Keep this one
                </button>
              </div>
            ))}
          </div>
          <span className="muted">
            Click a card to see it in the viewport; the others are discarded when you keep one.
          </span>
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

      <div className="project-layout">
        <div className="stack">
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
            onRegion={(next) => {
              if (!paintMode) {
                setRegion(next);
                return;
              }
              if (next) setStrokes((all) => [...all, { colour, region: next }]);
            }}
          />

          <form className="card stack" onSubmit={sendCommand}>
            <strong>Describe what you want</strong>
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
                Build
              </button>
              <button
                className="btn"
                type="button"
                disabled={!!busy || !prompt.trim()}
                onClick={() => void buildVariants()}
                title="The same request answered three ways; keep the one you like"
              >
                3 variants
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
        </div>

        <div className="stack">
          <div className="card stack">
            <div className="row">
              <strong>Paint</strong>
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

          <Inspector
            size={size}
            target={activeVersion ? bodyOf(activeVersion) : null}
            disabled={!activeVersion || !!busy}
            onApply={applyDimensions}
          />

          <EngineerCard
            disabled={!activeVersion || !!busy}
            hasRegion={region !== null}
            onAsk={askEngineer}
            onApplyFix={applyFix}
            onAdapt={adaptMaterial}
            onLighten={lighten}
          />

          <FitTestCard
            projects={others}
            currentProjectId={projectId}
            disabled={!activeVersion || !!busy}
            onRun={runFitTest}
            onApplyFix={applyFix}
          />

          <SplitCard
            version={activeVersion}
            size={size ? { x: size.x, y: size.y, z: size.z } : null}
            disabled={!activeVersion || !modelUrl || !!busy}
            hasPrinter={printers.length > 0}
            onPreview={setCutPlanes}
            onCut={cutIntoParts}
            onDownload={downloadPart}
          />

          <div className="card stack">
            <strong>Print check</strong>
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

          <div className="card stack">
            <strong>Export</strong>
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

          {graph && (
            <div className="card stack">
              <div className="row">
                <strong>Where it came from</strong>
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

          <div className="card stack">
            <div className="row">
              <strong>Versions</strong>
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

          <div className="card stack">
            <strong>AI history</strong>
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
        </div>
      </div>
    </div>
  );
}
