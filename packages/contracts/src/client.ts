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
}

export const JOB_TERMINAL = new Set(["succeeded", "failed", "canceled"]);

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
