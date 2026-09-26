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
import { type LiveEvent, LiveRoom, liveUrl } from "./live.js";

export type Schemas = components["schemas"];
export type Project = Schemas["ProjectOut"];
export type ProjectSummary = Schemas["ProjectSummary"];
export type ProjectReference = Schemas["ReferenceOut"];
export type ProjectReferenceUpdate = Schemas["ReferenceUpdate"];
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
export type ProvenanceGraph = Schemas["ProvenanceGraphOut"];
export type Component = Schemas["ComponentOut"];
export type SignInMethods = Schemas["MethodsOut"];
export type CodeStarted = Schemas["CodeStarted"];
export type SignInSession = Schemas["SessionOut"];
export type OAuthStarted = Schemas["OAuthStarted"];
export type Me = Schemas["MeOut"];
export type EnclosureBody = Schemas["EnclosureBody"];
export type EnclosureAccepted = Schemas["EnclosureAccepted"];
export type Listing = Schemas["ListingOut"];
export type ListingBody = Schemas["ListingBody"];
export type ListingPatch = Schemas["ListingPatch"];
export type ListingCategory = ListingBody["category"];
export type CreatorProfile = Schemas["CreatorProfileOut"];
export type CreatorProfileBody = Schemas["CreatorProfileBody"];
export type CreatorPage = Schemas["CreatorPageOut"];
export type Order = Schemas["OrderOut"];
export type Acquired = Schemas["AcquiredOut"];
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
    placement?: {
      align: "centre" | "origin";
      offset_mm: number[];
      rotate_z_deg: number;
    } | null;
    candidates?: {
      label: string;
      placement: { align: "centre" | "origin"; offset_mm: number[]; rotate_z_deg: number };
      verdict: "collides" | "press" | "transition" | "sliding" | "loose" | "apart";
      max_penetration_mm: number;
      min_clearance_mm: number | null;
    }[];
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
export type PrintReport = Schemas["PrintReport"];
export type PrintDiagnosis = Schemas["Diagnosis"];
export type PrintTuning = Schemas["TuningOut"];
export type PrintSymptom = PrintReport["symptoms"] extends (infer S)[] | undefined ? S : never;
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
/** Result of Mesh -> editable CAD (F-024/F-011). */
export interface ReconstructionResult {
  version_id: string;
  source_version_id: string;
  model_asset_id: string;
  source_asset_id: string;
  features: {
    faces: number;
    watertight: boolean;
    extents_mm: number[];
    planes: unknown[];
    cylinders: unknown[];
    edges: unknown[];
    threads: unknown[];
    patterns: unknown[];
    warnings: string[];
    reconstruction?: { fidelity: "prismatic" | "stepped" | "freeform"; levels: number; unexplained_levels: number } | null;
  };
  deviation: {
    tolerance_mm: number;
    mean_mm: number;
    p95_mm: number;
    max_mm: number;
    within_tolerance: number;
    samples: number;
  };
  plan: { operations: unknown[] };
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

  createPrimitive(
    projectId: string,
    body: {
      kind: "box" | "cylinder" | "sphere" | "cone" | "torus";
      width_mm?: number | null;
      depth_mm?: number | null;
      height_mm?: number | null;
      diameter_mm?: number | null;
      top_diameter_mm?: number | null;
      outer_diameter_mm?: number | null;
      tube_diameter_mm?: number | null;
      axis?: "x" | "y" | "z";
      centered?: boolean;
    },
  ) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/projects/${projectId}/primitives`, { body });
  }

  /** F-001: an organic mesh (figurine, animal, vase) from a description; 501 when the server has it off. */
  generateMesh(projectId: string, body: { prompt: string; size_mm?: number }) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/projects/${projectId}/generate-mesh`, { body });
  }

  getProject(projectId: string) {
    return this.request<ProjectSummary>("GET", `/api/v1/projects/${projectId}`);
  }

  getProjectReference(projectId: string) {
    return this.request<ProjectReference | null>("GET", `/api/v1/projects/${projectId}/reference`);
  }

  putProjectReference(projectId: string, body: ProjectReferenceUpdate) {
    return this.request<ProjectReference>("PUT", `/api/v1/projects/${projectId}/reference`, { body });
  }

  deleteProjectReference(projectId: string) {
    return this.request<void>("DELETE", `/api/v1/projects/${projectId}/reference`);
  }

  listVersions(projectId: string) {
    return this.request<Version[]>("GET", `/api/v1/projects/${projectId}/versions`);
  }

  /** F-079: versions, the commands and scans that made them, origins, listings, copies. */
  projectGraph(projectId: string) {
    return this.request<ProvenanceGraph>("GET", `/api/v1/projects/${projectId}/graph`);
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

  slicePreview(versionId: string, body: { printer_profile_id?: string | null } = {}) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/models/${versionId}/slice-preview`, { body });
  }

  sliceModel(versionId: string, body: Schemas["SliceBody"]) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/models/${versionId}/slice`, { body });
  }

  listPrintAnalyses(versionId: string) {
    return this.request<PrintAnalysis[]>("GET", `/api/v1/models/${versionId}/print-analyses`);
  }

  // --- scanning (E9) -----------------------------------------------------------------------

  startDemoScan(body: Schemas["DemoScanBody"]) {
    return this.request<Schemas["DemoScanOut"]>("POST", "/api/v1/scans/demo", { body });
  }

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

  // --- marketplace and creators (F-004 / F-065) ------------------------------------------------

  /** Published listings: words, category, creator, free only; newest, popular or cheapest. */
  searchListings(query: {
    q?: string;
    category?: ListingCategory;
    creator?: string;
    free?: boolean;
    sort?: "newest" | "popular" | "cheapest";
    limit?: number;
    offset?: number;
  } = {}) {
    return this.request<Listing[]>("GET", "/api/v1/marketplace/listings", {
      query: query as Record<string, string | number | boolean | undefined>,
    });
  }

  getListing(listingId: string) {
    return this.request<Listing>("GET", `/api/v1/listings/${listingId}`);
  }

  /** Put the project's head (or a kept version) on the shelf under a licence. */
  publishListing(projectId: string, body: ListingBody) {
    return this.request<Listing>("POST", `/api/v1/projects/${projectId}/listings`, { body });
  }

  projectListings(projectId: string) {
    return this.request<Listing[]>("GET", `/api/v1/projects/${projectId}/listings`);
  }

  updateListing(listingId: string, body: ListingPatch) {
    return this.request<Listing>("PATCH", `/api/v1/listings/${listingId}`, { body });
  }

  myListings() {
    return this.request<Listing[]>("GET", "/api/v1/me/listings");
  }

  /** Take a listing into a workspace of yours: a copy of the version with the credit written. */
  acquireListing(listingId: string, workspaceId: string) {
    return this.request<Acquired>("POST", `/api/v1/listings/${listingId}/acquire`, {
      body: { workspace_id: workspaceId },
    });
  }

  myOrders() {
    return this.request<Order[]>("GET", "/api/v1/me/orders");
  }

  myCreatorProfile() {
    return this.request<CreatorProfile>("GET", "/api/v1/me/creator-profile");
  }

  updateCreatorProfile(body: CreatorProfileBody) {
    return this.request<CreatorProfile>("PUT", "/api/v1/me/creator-profile", { body });
  }

  creatorPage(handle: string) {
    return this.request<CreatorPage>("GET", `/api/v1/creators/${encodeURIComponent(handle)}`);
  }

  followCreator(handle: string) {
    return this.request<CreatorProfile>(
      "POST",
      `/api/v1/creators/${encodeURIComponent(handle)}/follow`,
    );
  }

  unfollowCreator(handle: string) {
    return this.request<CreatorProfile>(
      "DELETE",
      `/api/v1/creators/${encodeURIComponent(handle)}/follow`,
    );
  }

  myFollowing() {
    return this.request<CreatorProfile[]>("GET", "/api/v1/me/following");
  }

  /** The newest listings of the creators you follow. */
  marketplaceFeed() {
    return this.request<Listing[]>("GET", "/api/v1/marketplace/feed");
  }

  // --- cut into parts (F-081) ------------------------------------------------------------------

  /** Cut the version's model into printable parts; the job result lists them. */
  splitModel(versionId: string, body: SplitBody) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/models/${versionId}/split`, {
      body,
    });
  }

  // --- sign-in (F-083): no token needed for these ---------------------------------------------

  signInMethods() {
    return this.request<SignInMethods>("GET", "/api/v1/auth/methods");
  }

  demoSignIn(body: {
    provider: "phone" | "email" | "yandex" | "vk";
    identifier: string;
    display_name?: string | null;
    locale?: string;
  }) {
    return this.request<SignInSession>("POST", "/api/v1/auth/demo", { body });
  }

  /** Ask for a one-time code; in demo mode the code comes back as `dev_code`. */
  requestCode(body: { channel: "phone" | "email"; address: string; locale?: string }) {
    return this.request<CodeStarted>("POST", "/api/v1/auth/codes", { body });
  }

  verifyCode(challengeId: string, code: string) {
    return this.request<SignInSession>("POST", `/api/v1/auth/codes/${challengeId}`, {
      body: { code },
    });
  }

  oauthStart(provider: "yandex" | "vk", redirectUri: string, locale?: string) {
    return this.request<OAuthStarted>("GET", `/api/v1/auth/oauth/${provider}/start`, {
      query: { redirect_uri: redirectUri, locale },
    });
  }

  oauthCallback(provider: "yandex" | "vk", code: string, state: string) {
    return this.request<SignInSession>("POST", `/api/v1/auth/oauth/${provider}/callback`, {
      body: { code, state },
    });
  }

  me() {
    return this.request<Me>("GET", "/api/v1/auth/me");
  }

  /** Settings: the name in the top bar and the language answers come in. */
  updateMe(body: { display_name?: string | null; locale?: string | null }) {
    return this.request<Me["user"]>("PATCH", "/api/v1/auth/me", { body });
  }

  logout() {
    return this.request<void>("POST", "/api/v1/auth/logout");
  }

  // --- components and enclosures (F-035/F-036) ------------------------------------------------

  /** The catalogue: boards, fans, displays, motors the platform knows the geometry of. */
  listComponents(q?: string, language: "en" | "ru" = "en") {
    const query = new URLSearchParams({ language });
    if (q) query.set("q", q);
    return this.request<Component[]>("GET", `/api/v1/components?${query}`);
  }

  /** A case around a catalogue component: tray on standoffs, ports open, lid that drops in.
   *  Without `project_id` a new project named after the component is created. */
  buildEnclosure(body: EnclosureBody, idempotencyKey?: string) {
    return this.request<EnclosureAccepted>("POST", "/api/v1/enclosures", {
      body,
      idempotencyKey,
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

  /** F-007: hollow the part to a wall the material carries, bosses kept around the holes. */
  optimizeModel(
    versionId: string,
    body: {
      goal?: "lighter";
      material_id?: string | null;
      printer_profile_id?: string | null;
      load?: "cosmetic" | "structural" | "load_bearing";
      opening?: "bottom" | "top" | "none";
      wall_mm?: number | null;
      language?: "en" | "ru";
      preview?: boolean;
    },
  ) {
    return this.request<AdaptMaterialResult>("POST", `/api/v1/models/${versionId}/optimize`, {
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

  /** Recognize manufacturing features and rebuild the mesh as an editable B-Rep. */
  reconstruct(
    versionId: string,
    body: { tolerance_mm?: number; max_levels?: number; samples?: number; threads?: boolean },
  ) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/models/${versionId}/reconstruct`, { body });
  }

  /**
   * Mesh formats for printing and engines; STEP/IGES are CAD-ready (F-078), B-Rep versions only.
   * `game` (GLB only, F-077) adds LODs, UVs, a PBR material and a collider for game engines.
   */
  exportModel(
    versionId: string,
    body: {
      format: "stl" | "glb" | "3mf" | "fbx" | "step" | "iges";
      printable?: boolean;
      game?: Partial<Schemas["GameExport"]> | null;
    },
  ) {
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

  // --- live project rooms (F-018) ---------------------------------------------------------------

  /** Join a project's live room; close the returned room when the page goes away. */
  liveRoom(
    projectId: string,
    onEvent: (event: LiveEvent) => void,
    onStatus?: (connected: boolean) => void,
  ): LiveRoom {
    if (!this.token) throw new Error("not signed in");
    return new LiveRoom(liveUrl(this.baseUrl, projectId), this.token, onEvent, onStatus);
  }

  // --- closed-loop printing (F-056) -------------------------------------------------------------

  /** How a print came out; the next slice of that material on this printer uses what it taught. */
  reportPrint(profileId: string, report: PrintReport) {
    return this.request<PrintDiagnosis>("POST", `/api/v1/printer-profiles/${profileId}/print-reports`, {
      body: report,
    });
  }

  /** Photos of the print; a vision model adds the defects it sees (501 without AI_PROVIDER=anthropic). */
  reportPrintPhotos(profileId: string, report: PrintReport & { photo_asset_ids: string[] }) {
    return this.request<Schemas["JobAccepted"]>("POST", `/api/v1/printer-profiles/${profileId}/print-photos`, {
      body: report,
    });
  }

  getTuning(profileId: string, materialId = "pla") {
    return this.request<PrintTuning>("GET", `/api/v1/printer-profiles/${profileId}/tuning`, {
      query: { material_id: materialId },
    });
  }

  resetTuning(profileId: string, materialId = "pla") {
    return this.request<PrinterProfile>("DELETE", `/api/v1/printer-profiles/${profileId}/tuning`, {
      query: { material_id: materialId },
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
