"use client";

/**
 * One scanner session, live (F-082): the fragments as they arrive, the device, the numbers;
 * then the fused model with its scale claim, and the way into the workspace.
 */
import { ScanProgressModal } from "@/components/ScanProgress";
import type { Job, Scan, ScanFrame } from "@physical-ai/contracts";
import { floorPlanMeasurements, parseFloorPlan, scanFrameWarnings } from "@physical-ai/contracts";
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
  const [roomShellUrl, setRoomShellUrl] = useState<string | null>(null);
  const [showEmptyRoom, setShowEmptyRoom] = useState(false);
  const [maskObject, setMaskObject] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progressOpen, setProgressOpen] = useState(false);
  const [progressSyncing, setProgressSyncing] = useState(false);
  const known = useRef(new Set<string>());
  const previousStatus = useRef<string | null>(null);
  const autoOpenedProgress = useRef(new Set<string>());

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
      if (current.room_shell_asset_id && !roomShellUrl) {
        setRoomShellUrl((await client.download(current.room_shell_asset_id)).url);
      } else if (!current.room_shell_asset_id) {
        setRoomShellUrl(null);
        setShowEmptyRoom(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [client, params.id, modelUrl, roomShellUrl]);

  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    if (!scan || !LIVE.has(scan.status)) return;
    const timer = setInterval(() => void refresh(), 2000);
    return () => clearInterval(timer);
  }, [scan, refresh]);

  const openProgress = useCallback(async () => {
    setProgressOpen(true);
    setProgressSyncing(true);
    try {
      await refresh();
    } finally {
      setProgressSyncing(false);
    }
  }, [refresh]);

  useEffect(() => {
    if (!scan || !["reconstructing", "failed", "canceled"].includes(scan.status)) return;
    const key = `${scan.job_id ?? scan.id}:${scan.status}`;
    if (autoOpenedProgress.current.has(key)) return;
    autoOpenedProgress.current.add(key);
    void openProgress();
  }, [openProgress, scan]);

  async function finish() {
    if (!client || !scan) return;
    setBusy("Reconstructing");
    setError(null);
    try {
      if (typeof Notification !== "undefined" && Notification.permission === "default") {
        void Notification.requestPermission();
      }
      const subject = (scan.capabilities as { subject?: unknown }).subject;
      const accepted = await client.finalizeScan(scan.id, {
        mask_object:
          scan.mode !== "scanner" &&
          subject === "object" &&
          frames.some((frame) => frame.kind === "rgb")
            ? maskObject
            : false,
      });
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
    provider?: string;
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
    mask?: {
      mask_applied?: boolean;
      model?: string;
      frames_masked?: number;
    };
    multi_view?: {
      registered_images?: number;
      registered_fraction?: number;
      mean_reprojection_error_px?: number | null;
      registered_by_section?: Record<string, number>;
    };
  } | null;
  const live = LIVE.has(scan.status);
  const language: "ru" | "en" =
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru")
      ? "ru"
      : "en";
  const ru = language === "ru";
  const canMaskObject =
    scan.mode !== "scanner" &&
    (scan.capabilities as { subject?: unknown }).subject === "object" &&
    frames.some((frame) => frame.kind === "rgb");
  const frameWarnings = scanFrameWarnings(frames);
  const roomPlanStats = (scan.capture_stats as {
    room_plan?: {
      floor_height_mm?: number;
      floor_plan?: unknown;
      room_shell?: { outline_mm?: number[][]; wall_height_mm?: number };
    };
  }).room_plan;
  const shellSpec = roomPlanStats?.room_shell;
  const measuredPlan = parseFloorPlan(roomPlanStats?.floor_plan);
  const measuredHeightMm = roomPlanStats?.floor_height_mm ?? shellSpec?.wall_height_mm;
  const roomMeasurements = measuredPlan && measuredHeightMm
    ? floorPlanMeasurements(measuredPlan, measuredHeightMm)
    : null;
  const shellWidth = shellSpec?.outline_mm?.length
    ? Math.max(...shellSpec.outline_mm.map((point) => point[0])) - Math.min(...shellSpec.outline_mm.map((point) => point[0]))
    : null;
  const shellDepth = shellSpec?.outline_mm?.length
    ? Math.max(...shellSpec.outline_mm.map((point) => point[1])) - Math.min(...shellSpec.outline_mm.map((point) => point[1]))
    : null;
  return (
    <div className="project-layout">
      <ScanProgressModal
        open={progressOpen}
        status={scan.status}
        job={job}
        frameCount={scan.frame_count}
        errorMessage={
          (job?.error as { message?: string } | null)?.message ??
          (scan.error as { message?: string } | null)?.message
        }
        syncing={progressSyncing}
        pausing={busy === "Pausing"}
        language={language}
        onClose={() => setProgressOpen(false)}
        onPause={() => void pause()}
      />
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
          <div className="stack">
            {roomShellUrl && (
              <div className="row" role="group" aria-label={ru ? "Вид комнаты" : "Room view"}>
                <button className={`btn ${!showEmptyRoom ? "primary" : ""}`} type="button" onClick={() => setShowEmptyRoom(false)}>
                  {ru ? "Исходный скан" : "Captured scan"}
                </button>
                <button className={`btn ${showEmptyRoom ? "primary" : ""}`} type="button" onClick={() => setShowEmptyRoom(true)}>
                  {ru ? "Пустая комната" : "Empty room"}
                </button>
              </div>
            )}
            <ModelViewer url={showEmptyRoom ? roomShellUrl : modelUrl} format={showEmptyRoom ? "stl" : undefined} selected={[]} onSelect={() => undefined} />
            {showEmptyRoom && (
              <span className="muted" style={{ fontSize: 12 }}>
                {ru
                  ? "Точная оболочка стен и пола из RoomPlan. Мебель и детали поверхности скрыты; это не AI-очистка фотосканирования."
                  : "Exact RoomPlan wall-and-floor shell. Furniture and surface detail are hidden; this is not an AI-cleaned photo scan."}
              </span>
            )}
            {showEmptyRoom && shellWidth !== null && shellDepth !== null && shellSpec?.wall_height_mm && (
              <span className="chip mono" aria-label={ru ? "Размеры оболочки комнаты" : "Room shell dimensions"}>
                {(shellWidth / 1000).toFixed(2)} × {(shellDepth / 1000).toFixed(2)} × {(shellSpec.wall_height_mm / 1000).toFixed(2)} m
              </span>
            )}
            {roomMeasurements && (
              <section className="card stack" aria-label={ru ? "Размеры помещения после сканирования" : "Room measurements after scanning"}>
                <div>
                  <strong>{ru ? "Размеры помещения" : "Room measurements"}</strong>
                  <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                    {ru ? "По измерениям RoomPlan" : "Measured by RoomPlan"} · {(roomMeasurements.width_mm / 1000).toFixed(2)} × {(roomMeasurements.depth_mm / 1000).toFixed(2)} × {(roomMeasurements.ceiling_height_mm / 1000).toFixed(2)} m
                  </div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8 }}>
                  <div className="card" style={{ padding: 12 }}>
                    <span className="muted">{ru ? "Пол" : "Floor"}</span>
                    <strong style={{ display: "block", marginTop: 4 }}>{roomMeasurements.floor_area_m2.toFixed(2)} m²</strong>
                  </div>
                  <div className="card" style={{ padding: 12 }}>
                    <span className="muted">{ru ? "Потолок" : "Ceiling"}</span>
                    <strong style={{ display: "block", marginTop: 4 }}>{roomMeasurements.ceiling_area_m2.toFixed(2)} m²</strong>
                    <span className="muted" style={{ fontSize: 12 }}>{ru ? "высота" : "height"} {(roomMeasurements.ceiling_height_mm / 1000).toFixed(2)} m</span>
                  </div>
                </div>
                {roomMeasurements.rooms.map((room, index) => (
                  <div className="row" key={`${room.name}-${index}`} style={{ justifyContent: "space-between", alignItems: "center" }}>
                    <span>
                      <strong>{room.name || (ru ? `Помещение ${index + 1}` : `Room ${index + 1}`)}</strong>
                      <span className="muted" style={{ display: "block", fontSize: 12 }}>
                        {ru ? "габарит" : "bounds"} {(room.width_mm / 1000).toFixed(2)} × {(room.depth_mm / 1000).toFixed(2)} m
                      </span>
                    </span>
                    <strong>{room.area_m2.toFixed(2)} m²</strong>
                  </div>
                ))}
                <div className="stack" style={{ gap: 8 }}>
                  <strong>{ru ? "Стены" : "Walls"}</strong>
                  {roomMeasurements.walls.map((wall) => (
                    <div className="row" key={wall.index} style={{ justifyContent: "space-between", alignItems: "center" }}>
                      <span>
                        <strong>{ru ? `Стена ${wall.index + 1}` : `Wall ${wall.index + 1}`}</strong>
                        <span className="muted" style={{ display: "block", fontSize: 12 }}>
                          {ru ? "длина" : "length"} {(wall.length_mm / 1000).toFixed(2)} m · {ru ? "высота" : "height"} {(wall.height_mm / 1000).toFixed(2)} m · {ru ? "толщина" : "thickness"} {Math.round(wall.thickness_mm)} mm
                        </span>
                      </span>
                      <strong>{wall.gross_area_m2.toFixed(2)} m²</strong>
                    </div>
                  ))}
                  <span className="muted" style={{ fontSize: 12 }}>
                    {ru ? "Площадь стен указана без вычета дверей и окон." : "Wall area is gross, before subtracting doors and windows."}
                  </span>
                </div>
              </section>
            )}
          </div>
        ) : (
          <FragmentsViewer fragments={fragments} />
        )}
      </div>
      <div className="stack">
        <div className="card stack">
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
            <div className="stack">
              {canMaskObject && (
                <label className="card row" style={{ alignItems: "flex-start" }}>
                  <input
                    type="checkbox"
                    checked={maskObject}
                    disabled={!!busy}
                    onChange={(event) => setMaskObject(event.target.checked)}
                  />
                  <span className="stack" style={{ gap: 2 }}>
                    <strong>{ru ? "Убрать фон перед реконструкцией" : "Remove the background before reconstruction"}</strong>
                    <span className="muted" style={{ fontSize: 12 }}>
                      {ru
                        ? "U²-Net отделит предмет от фона во всех кадрах для более чистой 3D-реконструкции. Это не ручная вырезка фотографии."
                        : "U²-Net separates the object from the background in every frame for a cleaner 3D reconstruction. This is not a manual photo cut-out tool."}
                    </span>
                  </span>
                </label>
              )}
              <div className="row">
                <button
                  className="btn primary"
                  type="button"
                  disabled={!!busy}
                  onClick={() => void finish()}
                >
                  {busy
                    ? busy
                    : canMaskObject
                      ? ru ? "Собрать модель" : "Build the model"
                      : ru ? "Завершить и собрать полученные фрагменты" : "Finish now — fuse what arrived"}
                </button>
                <span className="muted" style={{ fontSize: 12 }}>
                  {canMaskObject
                    ? ru ? "Обработка продолжится в фоне." : "Processing continues in the background."
                    : ru ? "Мост завершит сессию сам, когда устройство остановится." : "The bridge finishes on its own when the device stops."}
                </span>
              </div>
            </div>
          )}
          {scan.status === "reconstructing" && (
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="muted">
                {ru ? "3D-модель обрабатывается в фоне." : "The 3D model is processing in the background."}
              </span>
              <button
                className="btn primary"
                type="button"
                disabled={progressSyncing}
                onClick={() => void openProgress()}
              >
                {progressSyncing
                  ? ru ? "Обновляем…" : "Refreshing…"
                  : ru ? "Ход обработки" : "Processing status"}
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
          {scan.status === "ready" && report?.provider === "colmap_room" && report.multi_view && (
            <div className="card stack" style={{ gap: 6 }} aria-label={ru ? "Проверка фотосканирования комнаты" : "Photo-room scan review"}>
              <strong>{ru ? "Комната без LiDAR" : "Room without LiDAR"}</strong>
              <span className="status-green">
                {report.multi_view.registered_images ?? 0}/{scan.frame_count}{" "}
                {ru ? "кадров вошли в единое решение камер" : "frames joined one camera solution"}
              </span>
              <span className="muted" style={{ fontSize: 12 }}>
                {ru
                  ? "Масштаб задан измеренным максимальным пролётом, а не камерой. Проверьте стены, проёмы и швы текстуры перед сохранением."
                  : "Scale comes from the measured maximum span, not the camera. Inspect walls, openings, and texture seams before keeping it."}
              </span>
            </div>
          )}
          {report?.mask?.mask_applied === true && (
            <div className="status-green">
              {ru
                ? `Фон удалён U²-Net до реконструкции · кадров: ${report.mask.frames_masked ?? "—"}`
                : `Background removed by U²-Net before reconstruction · frames: ${report.mask.frames_masked ?? "—"}`}
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
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="status-red">
                {(scan.error as { message?: string } | null)?.message ?? "the scan failed"}
              </span>
              <button className="btn" type="button" onClick={() => void openProgress()}>
                {ru ? "Подробнее" : "Details"}
              </button>
            </div>
          )}
          {scan.status === "canceled" && (
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="status-yellow">Scan processing was canceled. Captured frames were kept.</span>
              <button className="btn" type="button" onClick={() => void openProgress()}>
                {ru ? "Подробнее" : "Details"}
              </button>
            </div>
          )}
          {error && <div className="error">{error}</div>}
        </div>
      </div>
    </div>
  );
}
