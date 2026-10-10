"use client";

/**
 * One scanner session, live (F-082): the fragments as they arrive, the device, the numbers;
 * then the fused model with its scale claim, and the way into the workspace.
 */
import { ScanProgress } from "@/components/ScanProgress";
import type { Job, Scan, ScanFrame } from "@physical-ai/contracts";
import { scanFrameWarnings } from "@physical-ai/contracts";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import type { FragmentSource } from "@/components/FragmentsViewer";
import { LoadingScreen } from "@/components/LoadingScreen";
import { useSession } from "@/lib/session";

const FragmentsViewer = dynamic(
  () => import("@/components/FragmentsViewer").then((m) => m.FragmentsViewer),
  { ssr: false },
);
const ModelViewer = dynamic(
  () => import("@/components/ModelViewer").then((m) => m.ModelViewer),
  { ssr: false },
);

const LIVE = new Set(["capturing", "uploading", "reconstructing"]);

export default function ScannerSessionPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { session, ready, client } = useSession();
  const [scan, setScan] = useState<Scan | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [frames, setFrames] = useState<ScanFrame[]>([]);
  const [fragments, setFragments] = useState<FragmentSource[]>([]);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const known = useRef(new Set<string>());
  const previousStatus = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client) return;
    try {
      const current = await client.getScan(params.id);
      setScan(current);
      if (
        previousStatus.current === "reconstructing" &&
        ["ready", "failed", "canceled", "paused"].includes(current.status) &&
        typeof Notification !== "undefined" &&
        Notification.permission === "granted" &&
        document.visibilityState !== "visible"
      ) {
        const complete = current.status === "ready";
        new Notification(
          complete
            ? "SOVA 3D: scan ready"
            : current.status === "paused"
              ? "SOVA 3D: scan paused"
              : "SOVA 3D: scan stopped",
          {
            body: complete
              ? "The reconstructed model is ready to review."
              : current.status === "canceled"
                ? "The scan processing was canceled."
                : current.status === "paused"
                  ? "Processing paused at a checkpoint — resume when ready."
                  : "The scan processing failed. Open SOVA 3D for details.",
          },
        );
      }
      previousStatus.current = current.status;
      // checkpoint_stage drives the "what will resume actually skip" hint below, so it
      // is only worth fetching while that hint is on screen (paused) or about to be.
      if (current.job_id && (current.status === "paused" || current.status === "reconstructing")) {
        setJob(await client.getJob(current.job_id));
      } else if (current.status !== "paused" && current.status !== "reconstructing") {
        setJob(null);
      }
      const list = await client.listScanFrames(params.id);
      setFrames(list);
      // new fragments get a download link once; the viewer keeps what it already has
      const fresh = list.filter((frame) => !known.current.has(frame.id));
      for (const frame of fresh) {
        let download;
        try {
          download = await client.download(frame.asset_id);
        } catch {
          continue; // a hiccup: the next poll asks again
        }
        known.current.add(frame.id);
        setFragments((all) => [
          ...all,
          {
            id: frame.id,
            url: download.url,
            kind: frame.kind,
            format: download.format ?? "stl",
            pose: frame.pose as Record<string, unknown>,
          },
        ]);
      }
      if (current.mesh_asset_id && !modelUrl) {
        setModelUrl((await client.download(current.mesh_asset_id)).url);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [client, params.id, modelUrl]);

  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    if (!scan || !LIVE.has(scan.status)) return;
    const timer = setInterval(() => void refresh(), 2000);
    return () => clearInterval(timer);
  }, [scan, refresh]);

  async function finish() {
    if (!client || !scan) return;
    setBusy("Reconstructing");
    setError(null);
    try {
      if (typeof Notification !== "undefined" && Notification.permission === "default") {
        void Notification.requestPermission();
      }
      const accepted = await client.finalizeScan(scan.id, {});
      previousStatus.current = "reconstructing";
      setScan({ ...scan, status: "reconstructing", job_id: accepted.job_id });
      await client.waitForJob(accepted.job_id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function cancel() {
    if (!client || !scan) return;
    setBusy("Cancelling");
    setError(null);
    try {
      setScan(await client.cancelScan(scan.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

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

  async function accept() {
    if (!client || !session || !scan) return;
    setBusy("Adding to the workspace");
    setError(null);
    try {
      let projectId = scan.project_id;
      if (!projectId) {
        const project = await client.createProject({
          workspace_id: session.workspaceId,
          name: scan.label ?? "Scanned object",
        });
        projectId = project.id;
      }
      const kept = await client.acceptScan(scan.id, { project_id: projectId, label: scan.label });
      router.push(`/projects/${kept.project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  if (!ready) return <LoadingScreen />;
  if (!session) {
    return (
      <div className="card">
        <p>Sign in to see the scan.</p>
      </div>
    );
  }
  if (!scan) return <div className="muted">{error ?? "Loading…"}</div>;

  const device = (scan.capabilities as { device?: Record<string, unknown> }).device ?? {};
  const report = scan.report as {
    scale?: {
      applied_mm?: number;
      source?: string;
      confidence?: number;
      warning?: string | null;
    };
    fusion?: string;
    faces?: number;
    noise_pieces_dropped?: number;
    watertight?: boolean;
    note?: string;
  } | null;
  const live = LIVE.has(scan.status);
  const language: "ru" | "en" =
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru")
      ? "ru"
      : "en";
  const ru = language === "ru";
  const frameWarnings = scanFrameWarnings(frames);
  return (
    <div className="project-layout">
      <div className="stack">
        <div>
          <h1 style={{ margin: 0 }}>{scan.label ?? "scan"}</h1>
          <span className="muted">
            <Link href="/scanner">Scanner station</Link> · {String(device.vendor ?? "")}{" "}
            {String(device.model ?? "")} · {scan.status}
            {live ? " · live" : ""}
          </span>
        </div>
        {scan.status === "ready" || scan.status === "accepted" ? (
          <ModelViewer url={modelUrl} selected={[]} onSelect={() => undefined} />
        ) : (
          <FragmentsViewer fragments={fragments} />
        )}
      </div>
      <div className="stack">
        <div className="card stack">
          <ScanProgress status={scan.status} language={language} />
          <strong>Scan</strong>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <span className="chip">{scan.frame_count} fragment(s)</span>
            {device.accuracy_mm !== undefined && device.accuracy_mm !== null && (
              <span className="chip mono">±{String(device.accuracy_mm)} mm</span>
            )}
            {device.turntable === true && <span className="chip muted">turntable</span>}
          </div>
          {frames.length > 0 && (
            <span className="muted" style={{ fontSize: 12 }}>
              last fragment {new Date(frames[frames.length - 1].created_at).toLocaleTimeString()}
              {typeof frames[frames.length - 1].pose?.azimuth_deg === "number"
                ? ` at ${Number(frames[frames.length - 1].pose.azimuth_deg).toFixed(0)}°`
                : ""}
            </span>
          )}
          {frameWarnings.length > 0 && (
            <div
              className="stack"
              style={{ gap: 6 }}
              aria-label={ru ? "Предупреждения по кадрам" : "Frame warnings"}
            >
              <span className="muted" style={{ fontSize: 12 }}>
                {ru ? "Проверьте отдельные кадры" : "Check individual frames"}
              </span>
              <div
                className="row"
                role="list"
                style={{ flexWrap: "nowrap", overflowX: "auto", paddingBottom: 2 }}
              >
                {frameWarnings.map((warning) => (
                  <span className="chip status-yellow" role="listitem" key={warning.sequenceNo}>
                    {ru ? "Кадр" : "Frame"} {warning.sequenceNo + 1} ·{" "}
                    {warning.codes
                      .map((code) =>
                        code === "blurry"
                          ? ru
                            ? "смазан"
                            : "blurred"
                          : ru
                            ? "движение камеры"
                            : "camera motion",
                      )
                      .join(" · ")}
                  </span>
                ))}
              </div>
            </div>
          )}
          {live && scan.status !== "reconstructing" && (
            <div className="row">
              <button
                className="btn primary"
                type="button"
                disabled={!!busy}
                onClick={() => void finish()}
              >
                {busy ? busy : "Finish now — fuse what arrived"}
              </button>
              <span className="muted" style={{ fontSize: 12 }}>
                The bridge finishes on its own when the device stops.
              </span>
            </div>
          )}
          {scan.status === "reconstructing" && (
            <div className="row">
              <span className="muted">Fusing the fragments…</span>
              <button
                className="btn"
                type="button"
                disabled={busy === "Pausing"}
                onClick={() => void pause()}
                title="Pauses at the next safe checkpoint — not instantly, same as Cancel"
              >
                {busy === "Pausing" ? "Pausing…" : "Pause"}
              </button>
            </div>
          )}
          {scan.status === "paused" && (
            <div className="stack" style={{ gap: 6 }}>
              <span className="status-yellow">
                Paused
                {job?.checkpoint_stage === "reconstructed"
                  ? " — resuming will skip reconstruction and continue from the saved mesh."
                  : " — resuming will start reconstruction over."}
              </span>
              <button
                className="btn primary"
                type="button"
                disabled={busy === "Resuming"}
                onClick={() => void resume()}
              >
                {busy === "Resuming" ? "Resuming…" : "Resume"}
              </button>
            </div>
          )}
          {live && (
            <button
              className="btn danger"
              type="button"
              disabled={busy === "Cancelling"}
              onClick={() => void cancel()}
            >
              {busy === "Cancelling" ? "Cancelling…" : "Cancel scan"}
            </button>
          )}
          {report?.scale && (
            <div className="stack" style={{ gap: 4 }}>
              <span>
                <strong>{report.scale.applied_mm?.toFixed(1)} mm</strong> across · scale from
                the {report.scale.source} (confidence {report.scale.confidence})
              </span>
              <span className="muted" style={{ fontSize: 12 }}>
                {report.fusion ? `fused by ${report.fusion}` : ""}
                {report.faces ? ` · ${report.faces} faces` : ""}
                {report.noise_pieces_dropped
                  ? ` · ${report.noise_pieces_dropped} speck(s) dropped`
                  : ""}
                {report.watertight === false
                  ? " · not closed yet — run Repair in the workspace"
                  : ""}
              </span>
              {report.scale.warning && <div className="status-yellow">{report.scale.warning}</div>}
              {report.note && (
                <span className="muted" style={{ fontSize: 12 }}>
                  {report.note}
                </span>
              )}
            </div>
          )}
          {scan.status === "ready" && (
            <button
              className="btn primary"
              type="button"
              disabled={!!busy}
              onClick={() => void accept()}
            >
              {busy ? busy : "Add to the workspace"}
            </button>
          )}
          {scan.status === "accepted" && scan.project_id && (
            <Link href={`/projects/${scan.project_id}`} className="btn primary">
              Open the project
            </Link>
          )}
          {scan.status === "failed" && (
            <div className="status-red">
              {(scan.error as { message?: string } | null)?.message ?? "the scan failed"}
            </div>
          )}
          {scan.status === "canceled" && (
            <div className="status-yellow">Scan processing was canceled. Captured frames were kept.</div>
          )}
          {error && <div className="error">{error}</div>}
        </div>
      </div>
    </div>
  );
}
