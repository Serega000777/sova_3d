"use client";

import type {
  AIHistoryItem,
  AIRequest,
  Job,
  PrintAnalysis,
  ProjectSummary,
  Version,
} from "@physical-ai/contracts";
import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { Inspector, type Size } from "@/components/Inspector";
import { useSession } from "@/lib/session";

const ModelViewer = dynamic(
  () => import("@/components/ModelViewer").then((m) => m.ModelViewer),
  { ssr: false },
);

type Busy = { label: string; job?: Job } | null;

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
  const [downloads, setDownloads] = useState<{ format: string; url: string }[]>([]);
  const [size, setSize] = useState<Size | null>(null);

  const refresh = useCallback(async () => {
    if (!client) return;
    const summary = await client.getProject(projectId);
    setProject(summary);
    const list = await client.listVersions(projectId);
    setVersions(list);
    setHistory(await client.listAiRequests(projectId));
    const head = summary.head_version ?? null;
    setActiveVersion((current) => list.find((v) => v.id === current?.id) ?? head);
  }, [client, projectId]);

  useEffect(() => {
    void refresh().catch((err) => setError(String(err)));
  }, [refresh]);

  // T-089: every accepted change is already a version server-side; poll so a version
  // created elsewhere (another device, a finished job) shows up without a reload.
  useEffect(() => {
    if (!client) return;
    const timer = setInterval(() => void refresh().catch(() => undefined), 15_000);
    return () => clearInterval(timer);
  }, [client, refresh]);

  // Load the active version's model + latest analysis.
  useEffect(() => {
    if (!client || !activeVersion) {
      setModelUrl(null);
      setAnalysis(null);
      return;
    }
    const model = activeVersion.assets.find((a) => a.role === "model") ?? activeVersion.assets[0];
    if (!model) {
      setModelUrl(null);
      return;
    }
    let cancelled = false;
    void client.download(model.asset_id).then((d) => !cancelled && setModelUrl(d.url));
    void client
      .listPrintAnalyses(activeVersion.id)
      .then((rows) => !cancelled && setAnalysis(rows[0] ?? null))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [client, activeVersion]);

  async function trackJob(label: string, jobId: string): Promise<Job> {
    if (!client) throw new Error("not signed in");
    setBusy({ label });
    try {
      return await client.waitForJob(jobId, { onProgress: (job) => setBusy({ label, job }) });
    } finally {
      setBusy(null);
    }
  }

  async function sendCommand(event: FormEvent) {
    event.preventDefault();
    if (!client || !prompt.trim()) return;
    setError(null);
    try {
      const accepted = await client.createAiCommand(projectId, {
        prompt: prompt.trim(),
        units: "mm",
        target: "print",
        selection_entity_ids: selected,
        project_version_id: activeVersion?.id ?? null,
      });
      const job = await trackJob("Planning & building", accepted.job_id);
      await afterAiJob(accepted.ai_request_id, job);
      setPrompt("");
    } catch (err) {
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
    const summary = await client.getProject(projectId);
    setActiveVersion(summary.head_version ?? null);
  }

  async function sendAnswer(event: FormEvent) {
    event.preventDefault();
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
      const summary = await client.getProject(projectId);
      setActiveVersion(summary.head_version ?? null);
    } else {
      setAnalysis((await client.listPrintAnalyses(activeVersion.id))[0] ?? null);
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
      });
      const job = await trackJob("Resizing", accepted.job_id);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string })?.message ?? "the edit failed");
        return;
      }
      await refresh();
      const summary = await client.getProject(projectId);
      setActiveVersion(summary.head_version ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function exportModel(format: "stl" | "3mf" | "glb") {
    if (!client || !activeVersion) return;
    setError(null);
    const accepted = await client.exportModel(activeVersion.id, { format, printable: format !== "glb" });
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

      <div className="project-layout">
        <div className="stack">
          <ModelViewer
            url={modelUrl}
            bodyId={activeVersion ? bodyOf(activeVersion) : "body"}
            selected={selected}
            onSelect={setSelected}
            onMeasure={setSize}
          />

          <form className="card stack" onSubmit={sendCommand}>
            <strong>Describe what you want</strong>
            <textarea
              className="textarea"
              placeholder="Органайзер 200×100×50 мм с 6 секциями, скругление 1.5 мм"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
            <div className="row">
              <button className="btn primary" type="submit" disabled={!!busy || !prompt.trim()}>
                Build
              </button>
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
              <form className="stack" onSubmit={sendAnswer}>
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
                    placeholder="Your answer"
                  />
                  <button className="btn" type="submit" disabled={!answer.trim() || !!busy}>
                    Answer
                  </button>
                </div>
              </form>
            )}
            {error && <div className="error">{error}</div>}
          </form>
        </div>

        <div className="stack">
          <Inspector
            size={size}
            target={activeVersion ? bodyOf(activeVersion) : null}
            disabled={!activeVersion || !!busy}
            onApply={applyDimensions}
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
            <div className="row">
              {(["stl", "3mf", "glb"] as const).map((format) => (
                <button key={format} className="btn" onClick={() => exportModel(format)} disabled={!activeVersion || !!busy}>
                  {format.toUpperCase()}
                </button>
              ))}
            </div>
            {downloads.map((d) => (
              <a key={d.url} href={d.url} className="mono">
                download {d.format}
              </a>
            ))}
          </div>

          <div className="card stack">
            <strong>Versions</strong>
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

          <div className="card stack">
            <strong>AI history</strong>
            <ul className="list">
              {history.map((h) => (
                <li key={h.id}>
                  <div>{h.prompt}</div>
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
