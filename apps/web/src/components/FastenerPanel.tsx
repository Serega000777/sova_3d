"use client";

import type {
  FastenerCatalogItem,
  FastenerCreate,
  FitTestReport,
  PhysicalAiClient,
  SceneGraph,
} from "@physical-ai/contracts";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  exactPlanarHoles,
  fastenerAcceptedMatches,
  verifiedFastenerAssembly,
  verifiedFastenerFit,
  verifiedFastenerVersion,
  type ExactPlanarHole,
} from "@/lib/fastener-fit";

const HEADS = ["socket_cap", "pan", "countersunk"] as const;
const DRIVES = ["hex", "phillips", "torx"] as const;

type Props = {
  client: PhysicalAiClient;
  workspaceId: string;
  versionId: string;
  canRun: boolean;
  language: "ru" | "en";
  onCreatedAssembly: (scene: SceneGraph) => Promise<void>;
};

function reasonMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

export function FastenerPanel({
  client,
  workspaceId,
  versionId,
  canRun,
  language,
  onCreatedAssembly,
}: Props) {
  const ru = language === "ru";
  const revision = useRef(0);
  const [catalog, setCatalog] = useState<FastenerCatalogItem[]>([]);
  const [holes, setHoles] = useState<ExactPlanarHole[]>([]);
  const [size, setSize] = useState("M3");
  const [lengthMm, setLengthMm] = useState(12);
  const [head, setHead] = useState<(typeof HEADS)[number]>("socket_cap");
  const [drive, setDrive] = useState<(typeof DRIVES)[number]>("hex");
  const [holeId, setHoleId] = useState("");
  const [report, setReport] = useState<FitTestReport | null>(null);
  const [fitTestId, setFitTestId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"fit" | "assembly" | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const request = ++revision.current;
    setCatalog([]);
    setHoles([]);
    setReport(null);
    setFitTestId(null);
    setLoading(true);
    setBusy(null);
    setProgress(0);
    setError(null);
    void Promise.all([client.listFasteners(), client.getOperationStack(versionId)])
      .then(([items, stack]) => {
        if (revision.current !== request) return;
        const found = exactPlanarHoles(stack, versionId);
        const safeCatalog = items.filter((item) => (
          typeof item?.size === "string"
          && item.size.trim()
          && Number.isFinite(item.nominal_mm)
          && item.nominal_mm > 0
          && Number.isFinite(item.clearance_mm)
          && item.clearance_mm > 0
        ));
        setCatalog(safeCatalog);
        setHoles(found);
        setSize((current) => safeCatalog.some((item) => item.size === current) ? current : safeCatalog[0]?.size ?? "M3");
        setHoleId((current) => found.some((hole) => hole.id === current) ? current : found[0]?.id ?? "");
      })
      .catch((reason: unknown) => {
        if (revision.current === request) setError(reasonMessage(reason));
      })
      .finally(() => {
        if (revision.current === request) setLoading(false);
      });
    return () => { revision.current += 1; };
  }, [client, versionId]);

  const selected = useMemo(() => catalog.find((item) => item.size === size) ?? null, [catalog, size]);
  const selectedHole = holes.find((hole) => hole.id === holeId) ?? null;
  const compatible = report?.fastener?.geometry_compatible === true;
  const validLength = Number.isFinite(lengthMm) && lengthMm >= 2 && lengthMm <= 200;

  function invalidateResult() {
    revision.current += 1;
    setReport(null);
    setFitTestId(null);
    setProgress(0);
    setError(null);
    setBusy(null);
  }

  async function buildAndCheck() {
    if (!canRun || busy || !selected || !selectedHole || !validLength) return;
    const request = ++revision.current;
    const sourceVersionId = versionId;
    const requested: FastenerCreate = {
      workspace_id: workspaceId,
      size,
      length_mm: lengthMm,
      head,
      drive,
      label: `Fastener ${size}×${lengthMm}`,
    };
    setBusy("fit");
    setProgress(0);
    setReport(null);
    setFitTestId(null);
    setError(null);
    try {
      const accepted = await client.createFastener(requested, crypto.randomUUID());
      if (!fastenerAcceptedMatches(accepted, requested, workspaceId, selected)) {
        throw new Error(ru ? "Сервер принял другой крепёж." : "The server accepted a different fastener.");
      }
      const built = await client.waitForJob(accepted.job.job_id, {
        timeoutMs: 8 * 60_000,
        onProgress: (job) => {
          if (revision.current === request) setProgress(Math.min(45, Math.round(job.progress * 0.45)));
        },
      });
      if (revision.current !== request || versionId !== sourceVersionId) return;
      const fastenerVersionId = verifiedFastenerVersion(built, accepted, workspaceId);
      if (!fastenerVersionId) {
        throw new Error((built.error as { message?: string } | null)?.message ?? (ru ? "Крепёж не построен согласованно." : "The fastener build was not consistent."));
      }
      const fitAccepted = await client.startFastenerFit(sourceVersionId, {
        fastener_version_id: fastenerVersionId,
        hole_operation_id: selectedHole.id,
        wanted: "clearance",
        language,
      }, crypto.randomUUID());
      if (fitAccepted.type !== "fit_test") {
        throw new Error(ru ? "Сервер запустил другой тип проверки." : "The server started a different check type.");
      }
      const measured = await client.waitForJob(fitAccepted.job_id, {
        timeoutMs: 8 * 60_000,
        onProgress: (job) => {
          if (revision.current === request) setProgress(45 + Math.min(55, Math.round(job.progress * 0.55)));
        },
      });
      if (revision.current !== request || versionId !== sourceVersionId) return;
      const verified = verifiedFastenerFit(
        measured,
        fitAccepted.job_id,
        workspaceId,
        sourceVersionId,
        fastenerVersionId,
        selectedHole,
        requested,
        accepted.fastener,
      );
      if (!verified) {
        throw new Error((measured.error as { message?: string } | null)?.message ?? (ru ? "Отчёт посадки не связан с выбранным отверстием." : "The fit report is not bound to the selected hole."));
      }
      setReport(verified.report);
      setFitTestId(verified.fitTestId);
      setProgress(100);
    } catch (reason) {
      if (revision.current === request) setError(reasonMessage(reason));
    } finally {
      if (revision.current === request) setBusy(null);
    }
  }

  async function createAssembly() {
    if (!canRun || busy || !fitTestId || !compatible) return;
    const request = ++revision.current;
    const sourceVersionId = versionId;
    setBusy("assembly");
    setError(null);
    try {
      const scene = await client.createFitAssembly(
        fitTestId,
        `Installed ${report?.fastener?.fastener.size ?? size}×${report?.fastener?.fastener.length_mm ?? lengthMm}`,
      );
      if (revision.current !== request || versionId !== sourceVersionId) return;
      const verified = verifiedFastenerAssembly(scene, sourceVersionId);
      if (!verified) throw new Error(ru ? "Сервер вернул несогласованную сборку." : "The server returned an inconsistent assembly.");
      await onCreatedAssembly(verified);
    } catch (reason) {
      if (revision.current === request) setError(reasonMessage(reason));
    } finally {
      if (revision.current === request) setBusy(null);
    }
  }

  return (
    <div className="stack" data-testid="fastener-panel" data-version-id={versionId}>
      <span className="muted">
        {ru
          ? "Выберите активное точное CAD-отверстие. Сервер построит отдельное тело крепежа, поставит его в сохранённую позу грани и измерит геометрию."
          : "Choose an active exact-CAD hole. The server builds a separate fastener solid, places it in the saved face pose, and measures the geometry."}
      </span>
      {loading && <span className="muted">{ru ? "Загружаем точные отверстия…" : "Loading exact holes…"}</span>}
      {!loading && holes.length === 0 && (
        <div className="card stack">
          <strong>{ru ? "Нет поддерживаемого отверстия" : "No supported hole"}</strong>
          <span className="muted">
            {ru
              ? "Нужна активная операция add_hole на плоской грани ±X/±Y/±Z. Отверстия импортированной сетки не угадываются."
              : "An active add_hole operation on a flat ±X/±Y/±Z face is required. Imported mesh holes are not guessed."}
          </span>
        </div>
      )}
      {holes.length > 0 && (
        <>
          <label className="stack" style={{ gap: 4 }}>
            <strong>{ru ? "Точное отверстие" : "Exact hole"}</strong>
            <select className="input" value={holeId} disabled={Boolean(busy)} onChange={(event) => { setHoleId(event.target.value); invalidateResult(); }}>
              {holes.map((hole) => (
                <option key={hole.id} value={hole.id}>
                  {hole.id} · {hole.faceSign}{hole.faceAxis.toUpperCase()} · Ø{hole.diameterMm} mm · {hole.positionMm.join(" × ")}
                </option>
              ))}
            </select>
          </label>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <label className="stack" style={{ gap: 4 }}>
              <strong>{ru ? "Размер" : "Size"}</strong>
              <select className="input" value={size} disabled={Boolean(busy)} onChange={(event) => { setSize(event.target.value); invalidateResult(); }}>
                {catalog.map((item) => <option key={item.size} value={item.size}>{item.size}</option>)}
              </select>
            </label>
            <label className="stack" style={{ gap: 4 }}>
              <strong>{ru ? "Длина, мм" : "Length, mm"}</strong>
              <input className="input" type="number" min={2} max={200} step="0.5" value={lengthMm} disabled={Boolean(busy)} onChange={(event) => { setLengthMm(Number(event.target.value)); invalidateResult(); }} />
            </label>
            <label className="stack" style={{ gap: 4 }}>
              <strong>{ru ? "Головка" : "Head"}</strong>
              <select className="input" value={head} disabled={Boolean(busy)} onChange={(event) => { setHead(event.target.value as (typeof HEADS)[number]); invalidateResult(); }}>
                {HEADS.map((value) => <option key={value} value={value}>{value.replace("_", " ")}</option>)}
              </select>
            </label>
            <label className="stack" style={{ gap: 4 }}>
              <strong>{ru ? "Шлиц" : "Drive"}</strong>
              <select className="input" value={drive} disabled={Boolean(busy)} onChange={(event) => { setDrive(event.target.value as (typeof DRIVES)[number]); invalidateResult(); }}>
                {DRIVES.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
          </div>
          {selected && <span className="muted">{ru ? "Номинал" : "Nominal"} Ø{selected.nominal_mm} · {ru ? "проходное" : "clearance"} Ø{selected.clearance_mm} mm</span>}
          {canRun ? (
            <button className="btn primary" type="button" disabled={Boolean(busy) || !selectedHole || !selected || !validLength} onClick={() => void buildAndCheck()}>
              {busy === "fit" ? (ru ? "Строим и измеряем…" : "Building and measuring…") : (ru ? "Проверить посадку" : "Check fit")}
            </button>
          ) : <span className="muted">{ru ? "Проверка доступна редактору проекта." : "Project editors can run this check."}</span>}
          {busy === "fit" && <progress aria-label={ru ? "Прогресс проверки крепежа" : "Fastener check progress"} value={progress} max={100} style={{ width: "100%" }} />}
        </>
      )}
      {error && <span className="error" role="alert">{error}</span>}
      {report?.fastener && (
        <div className="card stack">
          <strong className={compatible ? "status-green" : "status-red"}>
            {compatible ? (ru ? "Геометрическая посадка подходит" : "Geometric fit accepted") : (ru ? "Посадка не подходит" : "Fit rejected")}
          </strong>
          <span>{report.fastener.fastener.size}×{report.fastener.fastener.length_mm} · {report.fastener.fastener.head.replace("_", " ")} · {report.fastener.fastener.drive}</span>
          <span className="muted">{ru ? "Радиальный зазор" : "Radial clearance"}: {report.fastener.radial_clearance_mm} mm</span>
          <span className="muted">{ru ? "Глубина входа" : "Engagement depth"}: {report.fastener.engagement_mm} mm · {ru ? "головка на поверхности" : "head seated"}: {report.fastener.head_seated ? (ru ? "да" : "yes") : (ru ? "нет" : "no")}</span>
          {compatible && fitTestId && canRun && (
            <button className="btn primary" type="button" disabled={Boolean(busy)} onClick={() => void createAssembly()}>
              {busy === "assembly" ? (ru ? "Сохраняем сборку…" : "Saving assembly…") : (ru ? "Добавить крепёж в модель" : "Add fastener to model")}
            </button>
          )}
          <span className="muted">
            {ru
              ? "Стержень — гладкая номинальная оболочка. Резьба, шлиц, момент затяжки, преднатяг, прочность и сертификация не моделируются."
              : "The shank is a smooth nominal envelope. Threads, drive recess, torque, preload, strength, and certification are not modeled."}
          </span>
        </div>
      )}
    </div>
  );
}
