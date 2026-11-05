"use client";

import type {
  PhysicalAiClient,
  PrinterProfile,
  Project,
  Scan,
  Version,
} from "@physical-ai/contracts";
import { useEffect, useRef, useState } from "react";

import { ModelViewer } from "@/components/ModelViewer";
import {
  acceptedScanResults,
  physicalComparisonModelAsset,
  safeModelDownload,
  verifiedPhysicalComparison,
  type PhysicalComparisonReport,
} from "@/lib/physical-comparison";

const TOLERANCE_MM = 0.2;
const SAMPLES = 3000;

type Candidate = { project: Project; version: Version; scan: Scan };

type Props = {
  client: PhysicalAiClient;
  workspaceId: string;
  versionId: string;
  designModelUrl: string | null;
  designModelFormat: "stl" | "glb";
  canRun: boolean;
  language: "ru" | "en";
};

export function PhysicalComparisonPanel({
  client,
  workspaceId,
  versionId,
  designModelUrl,
  designModelFormat,
  canRun,
  language,
}: Props) {
  const ru = language === "ru";
  const revision = useRef(0);
  const downloadRevision = useRef(0);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [scanModel, setScanModel] = useState<{ url: string; format: "stl" | "glb" } | null>(null);
  const [printers, setPrinters] = useState<PrinterProfile[]>([]);
  const [printerId, setPrinterId] = useState("");
  const [report, setReport] = useState<PhysicalComparisonReport | null>(null);
  const [comparisonJobId, setComparisonJobId] = useState<string | null>(null);
  const [applied, setApplied] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"compare" | "calibrate" | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const request = ++revision.current;
    setLoading(true);
    setCandidates([]);
    setSelectedId("");
    setReport(null);
    setComparisonJobId(null);
    setApplied(null);
    setBusy(null);
    setProgress(0);
    setError(null);
    void Promise.all([
      client.listProjects(workspaceId),
      client.listPrinterProfiles(workspaceId),
      client.listScans(workspaceId, 200),
    ]).then(async ([projects, profiles, scans]) => {
      const accepted = acceptedScanResults(scans);
      const versions = await Promise.all([...accepted.keys()].filter((id) => id !== versionId).map((id) => client.getVersion(id)));
      if (revision.current !== request) return;
      const projectById = new Map(projects.map((project) => [project.id, project]));
      const rows = versions.flatMap((version) => {
        const project = projectById.get(version.project_id);
        const scan = accepted.get(version.id);
        return project && scan && physicalComparisonModelAsset(version) ? [{ project, version, scan }] : [];
      });
      setCandidates(rows);
      setSelectedId(rows[0]?.version.id ?? "");
      setPrinters(profiles);
      setPrinterId(profiles.find((profile) => profile.is_default)?.id ?? profiles[0]?.id ?? "");
    }).catch((reason: unknown) => {
      if (revision.current === request) setError(reason instanceof Error ? reason.message : String(reason));
    }).finally(() => {
      if (revision.current === request) setLoading(false);
    });
    return () => { revision.current += 1; };
  }, [client, workspaceId, versionId]);

  useEffect(() => {
    const request = ++downloadRevision.current;
    setScanModel(null);
    const candidate = candidates.find((item) => item.version.id === selectedId);
    const asset = candidate ? physicalComparisonModelAsset(candidate.version) : null;
    if (!asset) return;
    void client.download(asset.assetId).then((download) => {
      if (downloadRevision.current !== request) return;
      const url = safeModelDownload(download, asset);
      if (!url) throw new Error(ru ? "Файл принятого скана не прошёл проверку." : "The accepted scan file failed validation.");
      setScanModel({ url, format: asset.format });
    }).catch((reason: unknown) => {
      if (downloadRevision.current === request) setError(reason instanceof Error ? reason.message : String(reason));
    });
    return () => { downloadRevision.current += 1; };
  }, [client, candidates, selectedId, ru]);

  function selectCandidate(id: string) {
    revision.current += 1;
    setSelectedId(id);
    setReport(null);
    setComparisonJobId(null);
    setApplied(null);
    setError(null);
  }

  async function compare() {
    if (!selectedId || !canRun || busy) return;
    const request = ++revision.current;
    setBusy("compare");
    setProgress(0);
    setReport(null);
    setComparisonJobId(null);
    setApplied(null);
    setError(null);
    try {
      const accepted = await client.comparePhysicalScan(versionId, {
        scan_version_id: selectedId,
        tolerance_mm: TOLERANCE_MM,
        samples: SAMPLES,
      });
      const job = await client.waitForJob(accepted.job_id, {
        timeoutMs: 8 * 60_000,
        onProgress: (current) => {
          if (revision.current === request) setProgress(Math.max(0, Math.min(100, current.progress)));
        },
      });
      if (revision.current !== request) return;
      const verified = verifiedPhysicalComparison(job, versionId, selectedId, TOLERANCE_MM, SAMPLES);
      if (!verified) {
        const failure = job.error as { message?: string } | null;
        throw new Error(failure?.message ?? (ru ? "Сервер не вернул согласованный метрический отчёт." : "The server returned no consistent metric report."));
      }
      setReport(verified);
      setComparisonJobId(job.id);
      setProgress(100);
    } catch (reason) {
      if (revision.current === request) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      if (revision.current === request) setBusy(null);
    }
  }

  async function applyCalibration() {
    if (!comparisonJobId || !printerId || busy) return;
    const request = ++revision.current;
    setBusy("calibrate");
    setError(null);
    try {
      const profile = await client.calibratePrinterFromComparison(printerId, comparisonJobId);
      if (revision.current !== request) return;
      if (profile.id !== printerId) throw new Error(ru ? "Сервер обновил другой профиль." : "The server updated a different profile.");
      const shrinkage = Number((profile.calibration as Record<string, unknown>).shrinkage_pct);
      setApplied(Number.isFinite(shrinkage)
        ? `${profile.name}: ${shrinkage >= 0 ? "+" : ""}${shrinkage.toFixed(3)}%`
        : profile.name);
    } catch (reason) {
      if (revision.current === request) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      if (revision.current === request) setBusy(null);
    }
  }

  return (
    <div className="stack" data-testid="physical-comparison" data-version-id={versionId}>
      <span className="muted">
        {ru
          ? "Только отдельно принятый метрический post-print scan. Сервер совмещает позу, но не масштабирует сетку и не скрывает усадку."
          : "Accepted metric post-print scans only. The server aligns pose but never scales the mesh or hides shrinkage."}
      </span>
      {loading && <span className="muted">{ru ? "Ищем принятые метрические сканы…" : "Finding accepted metric scans…"}</span>}
      {!loading && candidates.length === 0 && <span className="muted">{ru ? "Сначала примите результат метрического скана напечатанной детали." : "Accept a metric scan of the printed part first."}</span>}
      {candidates.map(({ project, version, scan }) => (
        <button key={version.id} type="button" className={`btn${selectedId === version.id ? " primary" : ""}`} aria-pressed={selectedId === version.id} onClick={() => selectCandidate(version.id)} disabled={Boolean(busy)}>
          {project.name} · v{version.sequence_no} · {scan.label ?? (ru ? "метрический скан" : "metric scan")}
        </button>
      ))}
      {designModelUrl && scanModel && (
        <div className="physical-comparison-viewers" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10 }}>
          <div className="stack"><strong>{ru ? "Принятый метрический скан" : "Accepted metric scan"}</strong><div style={{ height: 260 }}><ModelViewer url={scanModel.url} format={scanModel.format} bodyId={`physical-scan-${selectedId}`} selected={[]} onSelect={() => undefined} showGrid={false} language={language} /></div></div>
          <div className="stack"><strong>{ru ? "Цифровая модель" : "Digital model"}</strong><div style={{ height: 260 }}><ModelViewer url={designModelUrl} format={designModelFormat} bodyId={`physical-design-${versionId}`} selected={[]} onSelect={() => undefined} showGrid={false} language={language} /></div></div>
        </div>
      )}
      {designModelUrl && scanModel && <span className="muted">{ru ? "Это два независимо кадрированных 3D-вида. Сервер считает совмещение после запуска; цветовой карты и оценки поверхности здесь нет." : "These are independently framed 3D views. The server computes registration after the run; no heat map or surface-quality score is implied."}</span>}
      {canRun ? (
        <button className="btn primary" type="button" disabled={Boolean(busy) || !selectedId} onClick={() => void compare()}>
          {busy === "compare" ? (ru ? "Совмещаем и измеряем…" : "Registering and measuring…") : (ru ? "Сравнить геометрию" : "Compare geometry")}
        </button>
      ) : <span className="muted">{ru ? "Запуск доступен редактору проекта." : "Project editors can run the comparison."}</span>}
      {busy === "compare" && <progress aria-label={ru ? "Прогресс метрического сравнения" : "Metric comparison progress"} value={progress} max={100} style={{ width: "100%" }} />}
      {error && <span className="error" role="alert">{error}</span>}
      {report && (
        <div className="stack">
          <strong>{Math.round(report.within_tolerance * 100)}% {ru ? "точек в допуске" : "of points within tolerance"} ±{report.tolerance_mm} mm</strong>
          <span>mean {report.mean_mm.toFixed(3)} · p95 {report.p95_mm.toFixed(3)} · max {report.max_mm.toFixed(3)} mm</span>
          <span className="muted">RMS {ru ? "совмещения" : "registration"}: {report.registration_rms_mm.toFixed(3)} mm</span>
          <span className="muted">{ru ? "Ошибка габаритов X/Y/Z" : "X/Y/Z size error"}: {report.size_error_mm.map((value) => `${value >= 0 ? "+" : ""}${value.toFixed(3)}`).join(" · ")} mm</span>
          <span className="muted">{ru ? "Масштаб заблокирован: отчёт не компенсирует усадку изменением scan mesh." : "Scale is locked: the report does not hide shrinkage by resizing the scan mesh."}</span>
        </div>
      )}
      {report && printers.length > 0 && (
        <div className="stack">
          <strong>{ru ? "Откалибровать принтер" : "Calibrate printer"}</strong>
          <span className="muted">{ru ? "Только безопасная равномерная поправка усадки X/Y. Отверстия, поток, температура и Z не меняются." : "Only a safe uniform X/Y shrinkage correction is applied. Holes, flow, temperature and Z stay unchanged."}</span>
          <select className="input" value={printerId} disabled={Boolean(busy)} onChange={(event) => setPrinterId(event.target.value)}>
            {printers.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
          </select>
          <button className="btn" type="button" disabled={Boolean(busy) || !comparisonJobId || !printerId} onClick={() => void applyCalibration()}>{busy === "calibrate" ? (ru ? "Применяем…" : "Applying…") : (ru ? "Применить измеренную усадку" : "Apply measured shrinkage")}</button>
          {applied && <span>{ru ? "Профиль обновлён" : "Profile updated"}: {applied}</span>}
        </div>
      )}
    </div>
  );
}
