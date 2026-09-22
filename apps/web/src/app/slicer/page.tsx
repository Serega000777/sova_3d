"use client";

/**
 * Slicer (F-030 / F-031 / F-081 / F-028): one place to get any model ready for a printer —
 * the printability check with its score, the best orientation, cutting into parts that fit
 * the bed, and the 3MF/STL that goes to the printer software. Every step is the same
 * operation the model's own page offers; here they are lined up in printing order.
 */
import type { Job, PrinterProfile, Project } from "@physical-ai/contracts";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/lib/session";

type Report = {
  score?: { total: number; status: string; subscores: { name: string; score: number; reason: string }[] };
  warnings?: { code: string; severity: string; message: string }[];
  summary?: string;
  metrics?: { mass_g?: number | null; print_time_min?: number | null; total_cost?: number | null; currency?: string };
  recommended?: { orientation: { label: string } } | null;
};

type SlicePreview = {
  layer_height_mm: number;
  total_layers: number;
  bounds_mm: number[];
  sampled_layers: { index: number; z_mm: number; paths: number[][][] }[];
  preview_only: true;
};

export default function SlicerPage() {
  const { session, ready, client } = useSession();
  const [projects, setProjects] = useState<Project[]>([]);
  const [printers, setPrinters] = useState<PrinterProfile[]>([]);
  const [printerId, setPrinterId] = useState<string>("");
  const [projectId, setProjectId] = useState<string>("");
  const [versionId, setVersionId] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloads, setDownloads] = useState<{ format: string; url: string }[]>([]);
  const [parts, setParts] = useState<{ name: string; extents_mm: number[]; fits_bed?: boolean }[] | null>(null);
  const [slices, setSlices] = useState<SlicePreview | null>(null);
  const [sliceIndex, setSliceIndex] = useState(0);

  const refresh = useCallback(async () => {
    if (!client || !session) return;
    try {
      const [all, profiles] = await Promise.all([
        client.listProjects(session.workspaceId),
        client.listPrinterProfiles(session.workspaceId),
      ]);
      const withModel = all.filter((project) => project.head_version_id);
      setProjects(withModel);
      setPrinters(profiles);
      if (!printerId && profiles[0]) setPrinterId(profiles[0].id);
      if (!projectId && withModel[0]) setProjectId(withModel[0].id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [client, session, printerId, projectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const project = projects.find((p) => p.id === projectId);
    setVersionId(project?.head_version_id ?? null);
    setReport(null);
    setParts(null);
    setDownloads([]);
    setSlices(null);
  }, [projectId, projects]);

  useEffect(() => { setSlices(null); }, [printerId]);

  async function track(label: string, jobId: string): Promise<Job> {
    setBusy(label);
    try {
      return await client!.waitForJob(jobId, {
        onProgress: (job) => setBusy(`${label} · ${job.progress}%`),
      });
    } finally {
      setBusy(null);
    }
  }

  async function analyze() {
    if (!client || !versionId) return;
    setError(null);
    try {
      const accepted = await client.analyzePrint(versionId, { printer_profile_id: printerId || null });
      const job = await track("Проверяем печать", accepted.job_id);
      if (job.status !== "succeeded") throw new Error((job.error as { message?: string })?.message ?? "проверка не удалась");
      setReport((job.result as { report?: Report })?.report ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function orient() {
    if (!client || !versionId) return;
    setError(null);
    try {
      const accepted = await client.optimizePrint(versionId, { printer_profile_id: printerId || null, apply: true });
      const job = await track("Подбираем ориентацию", accepted.job_id);
      if (job.status !== "succeeded") throw new Error((job.error as { message?: string })?.message ?? "ориентация не подобрана");
      const result = job.result as { version_id?: string; report?: Report };
      if (result.version_id) setVersionId(result.version_id);
      setReport(result.report ?? null);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function cut(mode: "fit" | "half") {
    if (!client || !versionId) return;
    setError(null);
    try {
      const accepted = await client.splitModel(versionId, {
        fit_bed: mode === "fit",
        printer_profile_id: mode === "fit" ? printerId || null : null,
        parts: mode === "fit" ? null : 2,
        margin_mm: 5,
        gap_mm: 10,
        repair: true,
        preview: false,
      });
      const job = await track(mode === "fit" ? "Режем под стол принтера" : "Режем пополам", accepted.job_id);
      if (job.status !== "succeeded") throw new Error((job.error as { message?: string })?.message ?? "не удалось разрезать");
      const result = job.result as { version_id?: string; parts?: { name: string; extents_mm: number[]; fits_bed?: boolean }[] };
      setParts(result.parts ?? []);
      if (result.version_id) setVersionId(result.version_id);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function exportFor(format: "3mf" | "stl") {
    if (!client || !versionId) return;
    setError(null);
    try {
      const accepted = await client.exportModel(versionId, { format, printable: true });
      const job = await track(`Готовим ${format.toUpperCase()}`, accepted.job_id);
      if (job.status !== "succeeded") throw new Error((job.error as { message?: string })?.message ?? "экспорт не удался");
      const download = await client.download((job.result as { asset_id: string }).asset_id);
      setDownloads((d) => [{ format, url: download.url }, ...d]);
      window.open(download.url, "_blank", "noopener");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function previewLayers() {
    if (!client || !versionId) return;
    setError(null);
    setSlices(null);
    try {
      const accepted = await client.slicePreview(versionId, { printer_profile_id: printerId || null });
      const job = await track("Строим сечения по слоям", accepted.job_id);
      if (job.status !== "succeeded") throw new Error((job.error as { message?: string })?.message ?? "не удалось нарезать модель");
      setSlices(job.result as SlicePreview);
      setSliceIndex(0);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  if (!ready) return null;
  if (!session) {
    return (
      <div className="empty-stage">
        <h1>Слайсер</h1>
        <Link className="btn primary" href="/login">
          Войти
        </Link>
      </div>
    );
  }

  const project = projects.find((p) => p.id === projectId);

  return (
    <div className="stack">
      <div>
        <h2 style={{ margin: 0 }}>Слайсер</h2>
        <p className="muted" style={{ margin: "6px 0 0" }}>
          Подготовка модели к печати по порядку: проверка → ориентация → нарезка на части под стол →
          файл для принтера. Печатает ваш слайсер (Cura, PrusaSlicer, Bambu Studio) — отсюда он получает
          проверенный 3MF/STL с частями, уже уложенными на стол.
        </p>
      </div>

      <div className="card row" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
        <label className="stack" style={{ minWidth: 260 }}>
          <span className="muted">Модель</span>
          <select className="input" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="stack" style={{ minWidth: 220 }}>
          <span className="muted">Принтер</span>
          <select className="input" value={printerId} onChange={(e) => setPrinterId(e.target.value)}>
            {printers.length === 0 && <option value="">— профилей нет —</option>}
            {printers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <Link className="btn" href="/printers">
          Профили принтеров
        </Link>
        {project && (
          <Link className="btn" href={`/projects/${project.id}`}>
            Открыть модель
          </Link>
        )}
      </div>

      {projects.length === 0 && (
        <div className="card muted">
          Пока нет моделей с геометрией — создайте или импортируйте модель в разделе «Моделлинг».
        </div>
      )}
      {error && <div className="error">{error}</div>}
      {busy && <div className="card muted">{busy}</div>}

      <div className="grid">
        <div className="card stack">
          <strong>1 · Проверка печати</strong>
          <span className="muted">Тонкие стенки, нависания, мосты, масса и время — с учётом профиля принтера.</span>
          <button className="btn primary" disabled={!versionId || !!busy} onClick={() => void analyze()}>
            Проверить
          </button>
          {report?.score && (
            <>
              <div className={`score status-${report.score.status}`}>
                {Math.round(report.score.total)} <span className="muted" style={{ fontSize: 14 }}>/ 100 · {report.score.status}</span>
              </div>
              <div className="muted">{report.summary}</div>
              <ul className="list">
                {report.score.subscores.map((s) => (
                  <li key={s.name}>
                    <strong>{s.name}</strong> {Math.round(s.score)} — <span className="muted">{s.reason}</span>
                  </li>
                ))}
                {report.warnings?.map((w) => (
                  <li key={w.code} className={w.severity === "error" ? "status-red" : "status-yellow"}>
                    {w.message}
                  </li>
                ))}
              </ul>
              {report.metrics && (
                <div className="muted">
                  {report.metrics.mass_g != null && `${report.metrics.mass_g.toFixed(0)} г`}
                  {report.metrics.print_time_min != null && ` · ~${Math.round(report.metrics.print_time_min)} мин`}
                  {report.metrics.total_cost != null && ` · ${report.metrics.total_cost.toFixed(2)} ${report.metrics.currency ?? ""}`}
                </div>
              )}
            </>
          )}
        </div>

        <div className="card stack">
          <strong>2 · Ориентация</strong>
          <span className="muted">Повернуть модель так, чтобы поддержек и нависаний было меньше всего.</span>
          <button className="btn" disabled={!versionId || !!busy} onClick={() => void orient()}>
            Подобрать и применить
          </button>
          {report?.recommended && <div className="muted">Лучшая: {report.recommended.orientation.label}</div>}
        </div>

        <div className="card stack">
          <strong>3 · Нарезка на части</strong>
          <span className="muted">
            Модель больше стола — режем плоскостями на части со штифтами и раскладываем на столе срезом вниз.
          </span>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <button className="btn" disabled={!versionId || !!busy || !printerId} onClick={() => void cut("fit")}>
              Под стол принтера
            </button>
            <button className="btn" disabled={!versionId || !!busy} onClick={() => void cut("half")}>
              Пополам
            </button>
          </div>
          {parts && (
            <ul className="list">
              {parts.map((part) => (
                <li key={part.name}>
                  <strong>{part.name}</strong>{" "}
                  <span className="muted mono">{part.extents_mm.map((v) => v.toFixed(0)).join(" × ")} мм</span>
                  {part.fits_bed === false && <span className="status-yellow"> · не влезает</span>}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card stack">
          <strong>4 · Файл для принтера</strong>
          <span className="muted">3MF хранит части и раскладку; STL — универсальный.</span>
          <div className="row">
            <button className="btn primary" disabled={!versionId || !!busy} onClick={() => void exportFor("3mf")}>
              Скачать 3MF
            </button>
            <button className="btn" disabled={!versionId || !!busy} onClick={() => void exportFor("stl")}>
              Скачать STL
            </button>
          </div>
          {downloads.map((d) => (
            <a key={d.url} href={d.url} target="_blank" rel="noopener noreferrer" className="muted mono">
              {d.format.toUpperCase()} ↗
            </a>
          ))}
        </div>
        <div className="card stack slice-preview-card">
          <strong>5 · Слои модели</strong>
          <span className="muted">Сечения реальной геометрии с высотой слоя выбранного принтера. Это геометрический просмотр: поддержки, заполнение и G-code пока формируются во внешнем слайсере.</span>
          <button className="btn" disabled={!versionId || !!busy} onClick={() => void previewLayers()}>Показать слои</button>
          {slices && slices.sampled_layers.length > 0 && (() => {
            const layer = slices.sampled_layers[sliceIndex];
            const width = slices.bounds_mm[0] || 1;
            const depth = slices.bounds_mm[1] || 1;
            return <div className="slice-preview-result">
              <div className="muted">{slices.total_layers} слоёв по {slices.layer_height_mm} мм · сечения {slices.sampled_layers.length} уровней</div>
              <svg className="slice-preview-svg" viewBox={`-2 -2 ${width + 4} ${depth + 4}`} role="img" aria-label={`Сечение слоя ${layer.index}`}>
                <rect x="0" y="0" width={width} height={depth} fill="none" stroke="currentColor" strokeOpacity=".25" strokeWidth=".2" />
                {layer.paths.map((path, index) => <polyline key={index} points={path.map(([x, y]) => `${x},${depth - y}`).join(" ")} fill="none" stroke="#71a8ff" strokeWidth={Math.max(width, depth) / 220} strokeLinejoin="round" />)}
              </svg>
              <label className="stack"><span>Слой {layer.index} / {slices.total_layers} · Z {layer.z_mm.toFixed(2)} мм</span><input type="range" min="0" max={slices.sampled_layers.length - 1} value={sliceIndex} onChange={(event) => setSliceIndex(Number(event.target.value))} aria-label="Выбрать сечение" /></label>
              <span className="muted">{layer.paths.length} замкнутых контуров на выбранном уровне.</span>
            </div>;
          })()}
        </div>
      </div>
    </div>
  );
}
