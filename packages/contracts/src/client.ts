/**
 * Minimal typed API client shared by web, mobile and desktop (T-088).
 *
 * Types come from `api.d.ts` (generated from services/api via
 * `python -m app.cli openapi` + openapi-typescript). The client is a thin
 * fetch wrapper: bearer auth, the error envelope, Idempotency-Key, and typed
 * helpers for the endpoints the clients use most. Works in browsers, React
 * Native (Expo Go) and Node 18+ — it only needs global `fetch`.
 */
import type { components, paths } from "./api.js";

export type Schemas = components["schemas"];
export type Project = Schemas["ProjectOut"];
export type ProjectSummary = Schemas["ProjectSummary"];
export type Version = Schemas["VersionOut"];
export type Job = Schemas["JobOut"];
export type AIRequest = Schemas["AIRequestOut"];
export type AIHistoryItem = Schemas["AIHistoryItem"];
export type AICommandAccepted = Schemas["AICommandAccepted"];
export type PrintAnalysis = Schemas["AnalysisOut"];
export type PrinterModel = Schemas["PrinterModelOut"];
export type Material = Schemas["MaterialOut"];
export type PrinterProfile = Schemas["ProfileOut"];
export type Download = Schemas["DownloadOut"];
export type Usage = Schemas["UsageOut"];
export type UploadCreated = Schemas["UploadCreated"];
export type SplitBody = Schemas["SplitBody"];
/** One part of a cut model (F-081), as the job result and the version's provenance list it. */
export interface SplitPart {
  name: string;
  asset_id: string;
  extents_mm: number[];
  volume_mm3: number;
  cut_faces: number;
  dowel_holes: number;
  fits_bed: boolean | null;
  plate_offset_mm: number[];
}
export interface SplitDowel {
  name: string;
  asset_id: string;
  diameter_mm: number;
  length_mm: number;
}
export interface SplitProvenance {
  planes: { origin_mm: number[]; normal: number[]; axis: string | null; source: string }[];
  parts: SplitPart[];
  dowels: SplitDowel[];
  layout_extents_mm: number[] | null;
  warnings: string[];
  repaired: { changed?: boolean } | null;
}
export type Scan = Schemas["ScanOut"];
export type ScanFrame = Schemas["FrameOut"];
export type ScanCreate = Schemas["ScanCreate"];
export type ScanFrameCreate = Schemas["FrameCreate"];
export type ScanStatus = Schemas["ScanStatus"];
export type VersionComparison = Schemas["VersionComparison"];
export type RegionSelection = Schemas["RegionSelection"];
export type EngineeringReport = Schemas["EngineeringReportOut"];
export type Template = Schemas["TemplateOut"];
export type CalibrationPrint = Schemas["CalibrationPrintOut"];
export type FitTest = Schemas["FitTestOut"];
export type VariantAccepted = Schemas["VariantAccepted"];
export type AdaptMaterialResult = Schemas["AdaptMaterialOut"];
export type VariantsBody = Schemas["VariantsBody"];
/** Where a work comes from and what may be done with it (F-072/F-047). */
export interface Licence {
  id: string;
  name: string;
  url: string;
  commercial_use: boolean;
  derivatives: boolean;
  share_alike: boolean;
  attribution_required: boolean;
}
export interface LicenceTerms {
  licence: Licence;
  commercial_use: boolean;
  derivatives: boolean;
  share_alike: boolean;
  attribution_required: boolean;
  credits: string[];
  notes: string[];
  chain: {
    project_id: string;
    name: string;
    license_id: string | null;
    attribution: string | null;
    source_url: string | null;
  }[];
}
export type FitTestBody = Schemas["FitTestBody"];
/** What the fit test job returns (F-027). */
export interface FitTestReport {
  measured: {
    verdict: "collides" | "press" | "transition" | "sliding" | "loose" | "apart";
    max_penetration_mm: number;
    min_clearance_mm: number | null;
    interference_mm3: number | null;
    b_inside_a_fraction: number;
  };
  advice: {
    summary: string;
    recommendation: string | null;
    fix: { label: string; operations: Record<string, unknown>[] } | null;
    numbers: Record<string, number>;
  };
  wanted: string;
}
export type CalibrationMeasurements = Schemas["Measurements"];
export type TemplateStarted = Schemas["StartedOut"];
/** What the engineer says about one question or one finding (F-005). */
export interface EngineeringAnswer {
  intent: "walls" | "strength" | "material" | "fastener" | "fit" | "overview";
  verdict: "yes" | "no" | "unsure" | "info";
  language: "ru" | "en";
  summary: string;
  reasons: string[];
  recommendation: string | null;
  numbers: Record<string, number>;
  fix: { label: string; operations: Record<string, unknown>[] } | null;
  confidence: "high" | "medium" | "low";
}
export interface EngineeringReportBody {
  material_id: string;
  load: "cosmetic" | "structural" | "load_bearing";
  recommended_wall_mm: number;
  facts: {
    bbox_mm: number[];
    volume_mm3: number | null;
    watertight: boolean;
    walls: { min_mm: number; p5_mm: number; median_mm: number; thin_fraction: number } | null;
    region_walls: { median_mm: number; thin_fraction: number } | null;
    slenderness: number | null;
    mass_g: Record<string, number>;
  };
  holes: { operation_id: string; diameter_mm: number; fits: Record<string, string> }[];
  materials: { id: string; name: string; score: number; reasons: string[]; note: string; mass_g: number | null }[];
  recommendations: EngineeringAnswer[];
  answer: EngineeringAnswer | null;
}
export type LassoRegion = Schemas["LassoRegion"];
export type BoxRegion = Schemas["BoxRegion"];
export type VersionSnapshot = Schemas["VersionSnapshot"];
export type Asset = Schemas["AssetOut"];

export interface ApiErrorBody {
  error: { code: string; message: string; details: unknown; trace_id: string };
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details: unknown,
    public readonly traceId: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ClientOptions {
  baseUrl: string;
  token?: string;
  fetch?: typeof fetch;
}

type Query = Record<string, string | number | boolean | undefined>;

interface RequestOptions {
  query?: Query;
  body?: unknown;
  idempotencyKey?: string;
}

/** One entry of an OperationPlan; the API validates it against the operation registry. */
export type EditOperation = { type: string; [key: string]: unknown };
export interface EditBody {
  operations: EditOperation[];
  label?: string | null;
  /** T-052: build it, but leave it a draft the user accepts or rejects. */
  preview?: boolean;
}

export const JOB_TERMINAL = new Set(["succeeded", "failed", "canceled"]);

/** Web Crypto is present in browsers, Expo Go and Node 18+. */
export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes as unknown as ArrayBuffer);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export class PhysicalAiClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  token?: string;

  constructor(options: ClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.token = options.token;
    // Bind the default: browsers reject `fetch` called with a non-Window `this`.
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  async request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    const url = new URL(this.baseUrl + path);
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
    const headers: Record<string, string> = { Accept: "application/json" };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
    const doFetch = this.fetchImpl; // call detached so a caller-supplied fetch keeps its own `this`
    const response = await doFetch(url.toString(), {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    if (response.status === 204) return undefined as T;
    const text = await response.text();
    const payload: unknown = text ? JSON.parse(text) : null;
    if (!response.ok) {
      const envelope = payload as Partial<ApiErrorBody> | null;
      const error = envelope?.error;
      throw new ApiError(
        response.status,
        error?.code ?? "http_error",
        error?.message ?? response.statusText,
        error?.details,
        error?.trace_id ?? "",
      );
    }
    return payload as T;
  }

  // --- projects & versions -----------------------------------------------------------------

  listProjects(workspaceId: string) {
    return this.request<Project[]>("GET", "/api/v1/projects", { query: { workspace_id: workspaceId } });
  }

  createProject(body: paths["/api/v1/projects"]["post"]["requestBody"]["content"]["application/json"]) {
    return this.request<Project>("POST", "/api/v1/projects", { body });
  }

  getProject(projectId: string) {
    return this.request<ProjectSummary>("GET", `/api/v1/projects/${projectId}`);
  }

  listVersions(projectId: string) {
    return this.request<Version[]>("GET", `/api/v1/projects/${projectId}/versions`);
  }

  getVersion(versionId: string) {
    return this.request<Version>("GET", `/api/v1/versions/${versionId}`);
  }

  // --- AI commands ----------------------------------------------------------------------------

  createAiCommand(
    projectId: string,
    body: paths["/api/v1/projects/{project_id}/ai-commands"]["post"]["requestBody"]["content"]["application/json"],
    idempotencyKey?: string,
  ) {
    return this.request<AICommandAccepted>("POST", `/api/v1/projects/${projectId}/ai-commands`, {
      body,
      idempotencyKey,
    });
  }

  clarify(requestId: string, answers: string[]) {
    return this.request<AICommandAccepted>("POST", `/api/v1/ai-requests/${requestId}/clarify`, {
      body: { answers },
    });
  }

  getAiRequest(requestId: string) {
    return this.request<AIRequest>("GET", `/api/v1/ai-requests/${requestId}`);
  }

  listAiRequests(projectId: string) {
    return this.request<AIHistoryItem[]>("GET", `/api/v1/projects/${projectId}/ai-requests`);
  }

  // --- jobs -----------------------------------------------------------------------------------

  getJob(jobId: string) {
    return this.request<Job>("GET", `/api/v1/jobs/${jobId}`);
  }

  /** Poll until the job leaves the active states (or waits for input). */
  /** T-095: ask a job to stop; running work stops at its next checkpoint. */
  cancelJob(jobId: string) {
    return this.request<Job>("POST", `/api/v1/jobs/${jobId}/cancel`);
  }

  async waitForJob(
    jobId: string,
    options: { intervalMs?: number; timeoutMs?: number; onProgress?: (job: Job) => void } = {},
  ): Promise<Job> {
    const interval = options.intervalMs ?? 1000;
    const deadline = Date.now() + (options.timeoutMs ?? 5 * 60_000);
    for (;;) {
      const job = await this.getJob(jobId);
      options.onProgress?.(job);
      if (JOB_TERMINAL.has(job.status) || job.status === "waiting_input") return job;
      if (Date.now() > deadline) throw new ApiError(0, "timeout", `job ${jobId} did not finish`, null, "");
      await new Promise((resolve) => setTimeout(resolve, interval));
    }
  }

  // --- printing -------------------------------------------------------------------------------

  analyzePrint(versionId: string, body: { printer_profile_id?: string | null; material_id?: string | null } = {}) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/models/${versionId}/analyze-print`, { body });
  }

  optimizePrint(versionId: string, body: { printer_profile_id?: string | null; material_id?: string | null; apply?: boolean } = {}) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/models/${versionId}/optimize-print`, { body });
  }

  listPrintAnalyses(versionId: string) {
    return this.request<PrintAnalysis[]>("GET", `/api/v1/models/${versionId}/print-analyses`);
  }

  // --- scanning (E9) -----------------------------------------------------------------------

  createScan(body: ScanCreate, idempotencyKey?: string) {
    return this.request<Scan>("POST", "/api/v1/scans", { body, idempotencyKey });
  }

  listScans(workspaceId: string, limit = 50) {
    return this.request<Scan[]>("GET", "/api/v1/scans", {
      query: { workspace_id: workspaceId, limit },
    });
  }

  getScan(scanId: string) {
    return this.request<Scan>("GET", `/api/v1/scans/${scanId}`);
  }

  listScanFrames(scanId: string) {
    return this.request<ScanFrame[]>("GET", `/api/v1/scans/${scanId}/frames`);
  }

  /** Register an uploaded image as frame `sequence_no`; re-sending one is a no-op (T-078). */
  addScanFrame(scanId: string, body: ScanFrameCreate) {
    return this.request<ScanFrame>("POST", `/api/v1/scans/${scanId}/frames`, { body });
  }

  updateCaptureStats(scanId: string, stats: Record<string, unknown>) {
    return this.request<Scan>("PATCH", `/api/v1/scans/${scanId}/capture-stats`, {
      body: { stats },
    });
  }

  finalizeScan(
    scanId: string,
    body: { scale_hint_mm?: number | string | null; scale_confidence?: number | string | null } = {},
    idempotencyKey?: string,
  ) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/scans/${scanId}/finalize`, {
      body,
      idempotencyKey,
    });
  }

  acceptScan(scanId: string, body: { project_id?: string | null; label?: string | null } = {}) {
    return this.request<Scan>("POST", `/api/v1/scans/${scanId}/accept`, { body });
  }

  cancelScan(scanId: string) {
    return this.request<Scan>("POST", `/api/v1/scans/${scanId}/cancel`);
  }

  // --- preview / accept / reject (T-052) ------------------------------------------------

  /** Before and after for a preview: this version against the one it was built from. */
  compareVersion(versionId: string, against?: string) {
    return this.request<VersionComparison>("GET", `/api/v1/versions/${versionId}/compare`, {
      query: { against },
    });
  }

  /** Accept a draft: it becomes history and the project head follows it. */
  acceptVersion(versionId: string) {
    return this.request<Version>("POST", `/api/v1/versions/${versionId}/finalize`);
  }

  /** Reject a preview. Only a draft can go; finalized history never can. */
  discardVersion(versionId: string) {
    return this.request<void>("DELETE", `/api/v1/versions/${versionId}`);
  }

  // --- bring a model in, take a format out (E15) --------------------------------------------

  /**
   * Upload a model file the whole way: presign, PUT, verify (T-110). The browser hashes the
   * bytes, so the server can prove it stored what the user picked.
   */
  async uploadFile(workspaceId: string, file: File | Blob, filename: string, contentType: string) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const created = await this.createUpload({
      workspace_id: workspaceId,
      filename,
      content_type: contentType,
      byte_size: bytes.byteLength,
    });
    const doFetch = this.fetchImpl;
    const put = await doFetch(created.url, {
      method: "PUT",
      headers: { "Content-Type": contentType, ...created.headers },
      body: bytes,
    });
    if (!put.ok) throw new Error(`upload failed (${put.status})`);
    return this.completeUpload({ upload_id: created.upload_id, sha256: await sha256Hex(bytes) });
  }

  /** Turn an uploaded file into a version of this project (T-110). */
  importModel(projectId: string, body: { asset_id: string; label?: string | null }) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/projects/${projectId}/imports`, {
      body,
    });
  }

  /** Convert an uploaded file to another format (T-112); the job result carries the report. */
  convertAsset(assetId: string, format: string) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/assets/${assetId}/convert`, {
      body: { format },
    });
  }

  /** Colour a model (T-108, F-034); the shape is untouched and the paint is a new version. */
  paintModel(
    versionId: string,
    body: {
      strokes: { colour: string; region?: unknown }[];
      base_colour?: string | null;
      label?: string | null;
      /** Start from the bare model instead of on top of the version's paint. */
      replace?: boolean;
    },
  ) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/models/${versionId}/paint`, {
      body,
    });
  }

  // --- variants (F-075) ------------------------------------------------------------------------

  /** Several constructive answers to one request, each a preview to keep or discard. */
  createVariants(projectId: string, body: VariantsBody) {
    return this.request<VariantAccepted[]>("POST", `/api/v1/projects/${projectId}/variants`, {
      body,
    });
  }

  // --- licence and remix (F-072 / F-047) --------------------------------------------------------

  listLicences() {
    return this.request<Licence[]>("GET", "/api/v1/licences");
  }

  setProjectLicense(
    projectId: string,
    body: { license_id?: string | null; attribution?: string | null; source_url?: string | null },
  ) {
    return this.request<Project>("PUT", `/api/v1/projects/${projectId}/license`, { body });
  }

  /** What may be done with the work, given every licence in its remix chain. */
  projectLicense(projectId: string) {
    return this.request<LicenceTerms>("GET", `/api/v1/projects/${projectId}/license`);
  }

  /** A new project from this one's current model — if the licence allows it. */
  remixProject(projectId: string, name?: string | null) {
    return this.request<Project>("POST", `/api/v1/projects/${projectId}/remix`, {
      body: { name: name ?? null },
    });
  }

  // --- fit test (F-027) ------------------------------------------------------------------------

  /** Put part B against part A; the job result carries the verdict and the advice. */
  startFitTest(body: FitTestBody) {
    return this.request<Schemas["JobAccepted"]>("POST", "/api/v1/fit-tests", { body });
  }

  listFitTests(versionId: string) {
    return this.request<FitTest[]>("GET", `/api/v1/models/${versionId}/fit-tests`);
  }

  // --- cut into parts (F-081) ------------------------------------------------------------------

  /** Cut the version's model into printable parts; the job result lists them. */
  splitModel(versionId: string, body: SplitBody) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/models/${versionId}/split`, {
      body,
    });
  }

  // --- templates (F-070) -----------------------------------------------------------------------

  listTemplates() {
    return this.request<Template[]>("GET", "/api/v1/templates");
  }

  /** A new project whose first version is being built from a template's sentence. */
  startFromTemplate(body: {
    workspace_id: string;
    template_id: string;
    params?: Record<string, number>;
    language?: "en" | "ru";
    name?: string | null;
  }) {
    return this.request<TemplateStarted>("POST", "/api/v1/projects/from-template", { body });
  }

  /** F-016: make an earlier state the current one — "два часа назад", "v3", "before the hole". */
  rollback(projectId: string, expression: string) {
    return this.request<Version>("POST", `/api/v1/projects/${projectId}/rollback`, {
      body: { expression },
    });
  }

  /** Ask the engineer about a version (T-118, F-005); the job result carries the report. */
  askEngineer(
    versionId: string,
    body: {
      question?: string | null;
      purpose?: string | null;
      material_id?: string | null;
      region?: RegionSelection | null;
    },
  ) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/models/${versionId}/engineering`, {
      body,
    });
  }

  /** F-009: walls, floors, holes and corners changed for a material — a preview edit. */
  adaptMaterial(
    versionId: string,
    body: { material_id: string; printer_profile_id?: string | null; language?: "en" | "ru"; preview?: boolean },
  ) {
    return this.request<AdaptMaterialResult>("POST", `/api/v1/models/${versionId}/adapt-material`, {
      body,
    });
  }

  listEngineeringReports(versionId: string) {
    return this.request<EngineeringReport[]>("GET", `/api/v1/models/${versionId}/engineering`);
  }

  /** Manual parametric edit (T-055): typed operations replayed by the kernel. */
  createEdit(versionId: string, body: EditBody, idempotencyKey?: string) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/models/${versionId}/edits`, {
      body,
      idempotencyKey,
    });
  }

  repair(versionId: string) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/models/${versionId}/repair`);
  }

  exportModel(versionId: string, body: { format: "stl" | "glb" | "3mf"; printable?: boolean }) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/models/${versionId}/exports`, { body });
  }

  download(assetId: string) {
    return this.request<Download>("GET", `/api/v1/assets/${assetId}/download`);
  }

  listPrinterModels() {
    return this.request<PrinterModel[]>("GET", "/api/v1/printer-models");
  }

  listMaterials() {
    return this.request<Material[]>("GET", "/api/v1/materials");
  }

  listPrinterProfiles(workspaceId: string) {
    return this.request<PrinterProfile[]>("GET", "/api/v1/printer-profiles", { query: { workspace_id: workspaceId } });
  }

  createPrinterProfile(body: paths["/api/v1/printer-profiles"]["post"]["requestBody"]["content"]["application/json"]) {
    return this.request<PrinterProfile>("POST", "/api/v1/printer-profiles", { body });
  }

  updatePrinterProfile(
    profileId: string,
    body: paths["/api/v1/printer-profiles/{profile_id}"]["put"]["requestBody"]["content"]["application/json"],
  ) {
    return this.request<PrinterProfile>("PUT", `/api/v1/printer-profiles/${profileId}`, { body });
  }

  // --- per-printer calibration (F-028/F-029) ----------------------------------------------------

  /** A project with the calibration coupon being built for this printer. */
  startCalibrationPrint(profileId: string) {
    return this.request<CalibrationPrint>("POST", `/api/v1/printer-profiles/${profileId}/calibration-print`);
  }

  /** Caliper readings from the printed coupon; the profile comes back with what it learned. */
  recordCalibration(profileId: string, measurements: CalibrationMeasurements) {
    return this.request<PrinterProfile>("POST", `/api/v1/printer-profiles/${profileId}/calibration`, {
      body: measurements,
    });
  }

  usage(workspaceId: string) {
    return this.request<Usage>("GET", "/api/v1/usage", { query: { workspace_id: workspaceId } });
  }

  // --- uploads --------------------------------------------------------------------------------

  createUpload(body: paths["/api/v1/uploads"]["post"]["requestBody"]["content"]["application/json"]) {
    return this.request<UploadCreated>("POST", "/api/v1/uploads", { body });
  }

  completeUpload(body: paths["/api/v1/assets/complete"]["post"]["requestBody"]["content"]["application/json"]) {
    return this.request<Asset>("POST", "/api/v1/assets/complete", { body });
  }
}
