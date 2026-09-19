"use client";

import type {
  AIHistoryItem,
  AIRequest,
  EditBody,
  EngineeringAnswer,
  Job,
  PrintAnalysis,
  ProjectSummary,
  RegionSelection,
  Version,
  VersionComparison,
} from "@physical-ai/contracts";
import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { EngineerCard } from "@/components/EngineerCard";
import { Inspector, type Size } from "@/components/Inspector";
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
  const [regionMode, setRegionMode] = useState(false);
  const [region, setRegion] = useState<RegionSelection | null>(null);
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
    } | null;
    // T-115: an edit re-applies the paint; say so when part of it no longer lands.
    const lost = result?.paint?.unused_strokes?.length ?? 0;
    const plural = lost === 1 ? "stroke no longer lands" : "strokes no longer land";
    setNotice(lost ? `${lost} paint ${plural} on the new shape` : null);
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
        preview: previewMode,
        region,
      });
      const job = await trackJob("Planning & building", accepted.job_id);
      await afterAiJob(accepted.ai_request_id, job);
      setPrompt("");
      if (job.status === "succeeded") {
        setRegion(null);
        setRegionMode(false);
      }
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
    if (await showPreviewIfDraft(job)) return;
    await showResult(job);
  }

  /** T-052: a preview is built but not kept — show it next to what it would replace. */
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

  /** The engineer's fix is an ordinary edit: the same operations, the same kernel. */
  async function applyFix(fix: NonNullable<EngineeringAnswer["fix"]>) {
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
              <button className="btn primary" type="submit" disabled={!!busy || !prompt.trim()}>
                Build
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
