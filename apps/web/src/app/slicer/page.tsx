"use client";

/**
 * Slicer (F-030 / F-031 / F-081 / F-028): one place to get any model ready for a printer —
 * the printability check with its score, the best orientation, cutting into parts that fit
 * the bed, and the 3MF/STL that goes to the printer software. Every step is the same
 * operation the model's own page offers; here they are lined up in printing order.
 */
import type {
  Job,
  Material,
  PrintDiagnosis,
  PrintDispatch,
  PrintFarmPlan,
  PrinterBridge,
  PrinterState,
  PrintSymptom,
  PrinterProfile,
  Project,
  RegionSelection,
} from "@physical-ai/contracts";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { LoadingScreen } from "@/components/LoadingScreen";
import { shrinkPhoto } from "@/lib/photo";
import { useSession } from "@/lib/session";
import { parseToolpath, TOOLPATH_COLOURS, type ToolpathPreview } from "@/lib/toolpath";

const ModelViewer = dynamic(
  () => import("@/components/ModelViewer").then((module) => module.ModelViewer),
  { ssr: false },
);

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

type SliceStats = {
  total_layers: number;
  layer_height_mode?: "fixed" | "adaptive";
  min_layer_height_mm?: number;
  max_layer_height_mm?: number;
  filament_used_mm: number;
  filament_used_g: number;
  estimated_time_s: number;
  support_columns: number;
  support_type?: "grid" | "tree";
  support_branches?: number;
  support_trunks?: number;
  support_modifiers?: number;
  support_blocked_faces?: number;
  support_enforced_faces?: number;
  process_modifiers?: number;
  process_modified_layers?: number;
  material_assigned_regions?: number;
  travel_mm?: number;
  xy_compensation_mm?: number;
  shrinkage_pct?: number;
  flow_pct?: number;
  tuning?: Record<string, number>;
  brim_loops?: number;
  adhesion_mode?: "skirt" | "brim" | "mouse_ears" | "raft" | "none";
  brim_width_mm?: number;
  mouse_ear_diameter_mm?: number;
  mouse_ear_count?: number;
  mouse_ear_requested_count?: number;
  mouse_ear_rejected_count?: number;
  raft_layers?: number;
  raft_base_layers?: number;
  raft_interface_layers?: number;
  raft_base_layer_height_mm?: number;
  raft_interface_layer_height_mm?: number;
  raft_base_speed_pct?: number;
  raft_interface_speed_pct?: number;
  raft_margin_mm?: number;
  raft_air_gap_mm?: number;
  raft_base_density_pct?: number;
  raft_interface_density_pct?: number;
  raft_density_profiled?: boolean;
  adhesion_speed_pct?: number;
  solid_skin_paths?: number;
  gcode_bytes: number;
};

type SliceOutcome = {
  assetId: string;
  format: string;
  stats: SliceStats;
  url: string;
  materialId: string;
  profileId: string | null;
};

type SupportModifier = {
  mode: "block" | "enforce";
  region: RegionSelection["region"];
};

type ProcessModifier = {
  infill_density_pct: number;
  print_speed_pct: number;
  nozzle_temperature_offset_c: number;
  infill_pattern: "lines" | "honeycomb" | null;
  wall_count: number | null;
  material_slot: number | null;
  region: RegionSelection["region"];
};

type NestedPart = {
  name: string;
  extents_mm: number[];
  fits_bed?: boolean;
  plate_offset_mm?: number[];
  plate_rotation_deg?: 0 | 90;
  edge_clearance_mm?: number | null;
  nearest_clearance_mm?: number | null;
};

type NestingResult = {
  parts: NestedPart[];
  dowels?: {
    name: string;
    diameter_mm: number;
    plate_offset_mm?: number[];
  }[];
  layout_bed_mm?: number[] | null;
  layout_extents_mm?: number[] | null;
  minimum_edge_clearance_mm?: number | null;
  minimum_part_clearance_mm?: number | null;
  margin_mm?: number | null;
  gap_mm?: number;
};

function BedNestingPreview({ result }: { result: NestingResult }) {
  const bed = result.layout_bed_mm;
  if (!bed || bed.length < 2 || bed[0] <= 0 || bed[1] <= 0) return null;
  const [bedX, bedY] = bed;
  const margin = result.margin_mm ?? 0;
  const colours = ["#f28c28", "#4ca6ff", "#8ccf5f", "#d784f7", "#ffd166", "#4dd4ac"];
  const nearEdge = (result.minimum_edge_clearance_mm ?? margin) < 5;
  return (
    <div className="stack" aria-label="Раскладка деталей на столе принтера">
      <div className="row" style={{ flexWrap: "wrap" }}>
        <span className="chip">Стол {bedX.toFixed(0)} × {bedY.toFixed(0)} мм</span>
        <span className="chip">До соседних ≥ {(result.minimum_part_clearance_mm ?? 0).toFixed(1)} мм</span>
        <span className={`chip ${nearEdge ? "status-yellow" : ""}`}>
          До края ≥ {(result.minimum_edge_clearance_mm ?? 0).toFixed(1)} мм
        </span>
      </div>
      {nearEdge && <div className="status-yellow">Слишком близко к краю: увеличьте отступ и повторите раскладку.</div>}
      <svg
        viewBox={`0 0 ${bedX} ${bedY}`}
        role="img"
        aria-label={`Автораскладка ${result.parts.length} деталей без пересечений`}
        style={{ width: "100%", maxWidth: 560, border: "1px solid var(--line)", borderRadius: 10, background: "#181a1f" }}
      >
        <rect x={0} y={0} width={bedX} height={bedY} fill="#24272e" />
        {margin > 0 && (
          <rect
            x={margin}
            y={margin}
            width={Math.max(0, bedX - 2 * margin)}
            height={Math.max(0, bedY - 2 * margin)}
            fill="none"
            stroke="#7f8795"
            strokeDasharray="4 3"
            vectorEffect="non-scaling-stroke"
          />
        )}
        {result.parts.map((part, index) => {
          const offset = part.plate_offset_mm ?? [0, 0, 0];
          const rotated = part.plate_rotation_deg === 90;
          const width = rotated ? part.extents_mm[1] : part.extents_mm[0];
          const depth = rotated ? part.extents_mm[0] : part.extents_mm[1];
          return (
            <g key={part.name}>
              <rect
                x={offset[0]}
                y={offset[1]}
                width={width}
                height={depth}
                fill={colours[index % colours.length]}
                fillOpacity={0.72}
                stroke="#fff"
                vectorEffect="non-scaling-stroke"
              />
              <text
                x={offset[0] + width / 2}
                y={offset[1] + depth / 2}
                textAnchor="middle"
                dominantBaseline="middle"
                fill="#fff"
                fontSize={Math.max(5, Math.min(width, depth) / 5)}
              >
                {index + 1} · {part.plate_rotation_deg ?? 0}°
              </text>
            </g>
          );
        })}
        {result.dowels?.map((dowel) => {
          const offset = dowel.plate_offset_mm ?? [0, 0, 0];
          return (
            <circle
              key={dowel.name}
              cx={offset[0] + dowel.diameter_mm / 2}
              cy={offset[1] + dowel.diameter_mm / 2}
              r={dowel.diameter_mm / 2}
              fill="#e8edf5"
              stroke="#8d96a5"
              vectorEffect="non-scaling-stroke"
            />
          );
        })}
      </svg>
      <span className="muted">
        Ограничивающие прямоугольники не пересекаются; сервер проверил выбранные зазор и отступ до края.
      </span>
    </div>
  );
}

/** F-056: what a person sees on a finished print, in the words of the report form. */
const SYMPTOMS: { id: PrintSymptom; label: string }[] = [
  { id: "stringing", label: "Паутина / сопли" },
  { id: "warping", label: "Углы отклеились" },
  { id: "poor_adhesion", label: "Первый слой не прилип" },
  { id: "elephant_foot", label: "«Слоновья нога»" },
  { id: "under_extrusion", label: "Недоэкструзия, пропуски" },
  { id: "over_extrusion", label: "Переэкструзия, наплывы" },
  { id: "poor_overhangs", label: "Нависания провисли" },
  { id: "layer_shift", label: "Сдвиг слоёв" },
  { id: "dimensions_off", label: "Размеры не совпали" },
  { id: "clogging", label: "Засор сопла" },
];

/** The API explains in English; the page speaks Russian (same rules, same order). */
const SYMPTOM_HELP_RU: Record<string, { causes: string; advice: string }> = {
  stringing: { causes: "пластик подтекает при перемещениях; сопло слишком горячее для этого филамента", advice: "Если филамент щёлкает или шипит при печати — просушите его." },
  warping: { causes: "углы остывают и сжимаются быстрее, чем их держит стол", advice: "Уберите сквозняки; ABS и ASA печатайте в закрытом корпусе." },
  poor_adhesion: { causes: "первый слой печатается слишком быстро или слишком холодно, чтобы схватиться", advice: "Протрите стол спиртом и заново выставьте уровень или Z-offset." },
  elephant_foot: { causes: "первый слой придавлен и расплющен шире остальных", advice: "Если не пройдёт — чуть поднимите Z-offset." },
  under_extrusion: { causes: "до сопла доходит меньше пластика, чем нужно; сопло холодновато", advice: "Проверьте частичный засор и что катушка разматывается свободно." },
  over_extrusion: { causes: "пластика подаётся больше, чем нужно линиям", advice: "Измерьте диаметр филамента: по умолчанию считается 1,75 мм." },
  poor_overhangs: { causes: "расплавленный пластик провисает там, где под ним пусто", advice: "Включите поддержки или поверните модель («Подобрать и применить»), чтобы нависания легли вниз." },
  layer_shift: { causes: "механический пропуск шагов: ослаб ремень или шкив, или сопло задело печать", advice: "Подтяните ремни и винты шкивов; снизьте скорость в профиле принтера." },
  dimensions_off: { causes: "отверстия и наружные размеры у каждого принтера уходят по-своему", advice: "Напечатайте купон калибровки и введите замеры штангенциркулем: размеры правятся по измерениям, а не по догадке." },
  clogging: { causes: "тепло поднимается вверх по соплу или внутри мусор", advice: "Сделайте «холодную протяжку» или замените сопло; проверьте, что вентилятор хотэнда крутится." },
};

const TUNING_LABELS: Record<string, [string, string]> = {
  nozzle_offset_c: ["Сопло", "°C"],
  bed_offset_c: ["Стол", "°C"],
  retraction_mm: ["Ретракт", "мм"],
  flow_pct: ["Поток", "%"],
  brim_mm: ["Кайма", "мм"],
  elephant_foot_mm: ["Первый слой внутрь", "мм"],
  first_layer_speed_pct: ["Скорость 1-го слоя", "%"],
};

const TOOLPATH_LEGEND = [
  ["perimeter", "Периметр"],
  ["solid-infill", "Сплошное заполнение"],
  ["infill", "Заполнение"],
  ["support", "Поддержка"],
  ["support-interface", "Интерфейс поддержки"],
  ["skirt", "Юбка"],
  ["brim", "Кайма"],
  ["mouse-ear", "Ушки"],
  ["raft-base", "Основа рафта"],
  ["raft-interface", "Интерфейс рафта"],
  ["travel", "Холостой ход"],
  ["unknown", "Другое"],
] as const;

function describeTuning(tuning: Record<string, number> | undefined): string {
  return Object.entries(tuning ?? {})
    .map(([name, value]) => {
      const [label, unit] = TUNING_LABELS[name] ?? [name, ""];
      const signed = name.endsWith("_offset_c") && value > 0 ? `+${value}` : `${value}`;
      return `${label} ${signed} ${unit}`;
    })
    .join(" · ");
}

export default function SlicerPage() {
  const { session, ready, client } = useSession();
  const [projects, setProjects] = useState<Project[]>([]);
  const [printers, setPrinters] = useState<PrinterProfile[]>([]);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [printerId, setPrinterId] = useState<string>("");
  const [materialId, setMaterialId] = useState("pla");
  const [projectId, setProjectId] = useState<string>("");
  const [versionId, setVersionId] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloads, setDownloads] = useState<{ format: string; url: string }[]>([]);
  const [nesting, setNesting] = useState<NestingResult | null>(null);
  const [bedMarginMm, setBedMarginMm] = useState(5);
  const [partGapMm, setPartGapMm] = useState(10);
  const [slices, setSlices] = useState<SlicePreview | null>(null);
  const [sliceIndex, setSliceIndex] = useState(0);
  const [infillPct, setInfillPct] = useState(20);
  const [infillPattern, setInfillPattern] = useState<"lines" | "honeycomb">("lines");
  const [wallCount, setWallCount] = useState(2);
  const [topSolidLayers, setTopSolidLayers] = useState(4);
  const [bottomSolidLayers, setBottomSolidLayers] = useState(4);
  const [adaptiveLayerHeight, setAdaptiveLayerHeight] = useState(false);
  const [minLayerHeight, setMinLayerHeight] = useState(0.1);
  const [maxLayerHeight, setMaxLayerHeight] = useState(0.3);
  const [supports, setSupports] = useState(false);
  const [supportType, setSupportType] = useState<"grid" | "tree">("grid");
  const [supportPaintMode, setSupportPaintMode] = useState<"block" | "enforce" | null>(null);
  const [supportBrushMm, setSupportBrushMm] = useState(8);
  const [supportModifiers, setSupportModifiers] = useState<SupportModifier[]>([]);
  const [processPaintActive, setProcessPaintActive] = useState(false);
  const [processDensityPct, setProcessDensityPct] = useState(50);
  const [processSpeedPct, setProcessSpeedPct] = useState(100);
  const [processTemperatureOffsetC, setProcessTemperatureOffsetC] = useState(0);
  const [processWallCount, setProcessWallCount] = useState<number | "inherit">("inherit");
  const [processMaterialSlot, setProcessMaterialSlot] = useState<number | "inherit">("inherit");
  const [processInfillPattern, setProcessInfillPattern] = useState<
    "inherit" | "lines" | "honeycomb"
  >("inherit");
  const [processModifiers, setProcessModifiers] = useState<ProcessModifier[]>([]);
  const [adhesionMode, setAdhesionMode] = useState<
    "auto" | "skirt" | "brim" | "mouse_ears" | "raft" | "none"
  >("auto");
  const [brimWidthMm, setBrimWidthMm] = useState(5);
  const [mouseEarDiameterMm, setMouseEarDiameterMm] = useState(10);
  const [mouseEarPlacement, setMouseEarPlacement] = useState<"auto" | "manual">("auto");
  const [mouseEarPoints, setMouseEarPoints] = useState<[number, number, number][]>([]);
  const [adhesionSpeedPct, setAdhesionSpeedPct] = useState(100);
  const [raftMarginMm, setRaftMarginMm] = useState(5);
  const [raftBaseLayers, setRaftBaseLayers] = useState(1);
  const [raftInterfaceLayers, setRaftInterfaceLayers] = useState(1);
  const [raftBaseLayerHeightMm, setRaftBaseLayerHeightMm] = useState<number | null>(null);
  const [raftInterfaceLayerHeightMm, setRaftInterfaceLayerHeightMm] = useState<number | null>(
    null,
  );
  const [raftBaseSpeedPct, setRaftBaseSpeedPct] = useState(100);
  const [raftInterfaceSpeedPct, setRaftInterfaceSpeedPct] = useState(100);
  const [raftAirGapMm, setRaftAirGapMm] = useState(0.15);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [modelFormat, setModelFormat] = useState<"stl" | "glb">("stl");
  const [modelSize, setModelSize] = useState<{ x: number; y: number; z: number } | null>(null);
  const [gcode, setGcode] = useState<SliceOutcome | null>(null);
  const [toolpath, setToolpath] = useState<ToolpathPreview | null>(null);
  const [toolpathIndex, setToolpathIndex] = useState(0);
  const [showTravel, setShowTravel] = useState(false);
  const [outcome, setOutcome] = useState<"success" | "partial" | "failed">("partial");
  const [symptoms, setSymptoms] = useState<PrintSymptom[]>([]);
  const [diagnosis, setDiagnosis] = useState<PrintDiagnosis | null>(null);
  const [printPhotos, setPrintPhotos] = useState<File[]>([]);
  const [photoFindings, setPhotoFindings] = useState<{ symptom: string; evidence: string }[] | null>(null);
  const [bridge, setBridge] = useState<PrinterBridge | null>(null);
  const [startImmediately, setStartImmediately] = useState(false);
  const [dispatch, setDispatch] = useState<PrintDispatch | null>(null);
  const [printerState, setPrinterState] = useState<PrinterState | null>(null);
  const [cameraUrl, setCameraUrl] = useState<string | null>(null);
  const [batchQuantities, setBatchQuantities] = useState<Record<string, number>>({});
  const [batchPrinterIds, setBatchPrinterIds] = useState<string[]>([]);
  const [batchMaterialId, setBatchMaterialId] = useState("pla");
  const [batchPlan, setBatchPlan] = useState<PrintFarmPlan | null>(null);

  const refresh = useCallback(async () => {
    if (!client || !session) return;
    try {
      const [all, profiles, availableMaterials, printerBridge] = await Promise.all([
        client.listProjects(session.workspaceId),
        client.listPrinterProfiles(session.workspaceId),
        client.listMaterials(),
        client.getPrinterBridge(),
      ]);
      const withModel = all.filter((project) => project.head_version_id);
      setProjects(withModel);
      setPrinters(profiles);
      setMaterials(availableMaterials);
      setBridge(printerBridge);
      setBatchPrinterIds((current) => current.length > 0 ? current : profiles.map((profile) => profile.id));
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
    setReport(null);
    setNesting(null);
    setDownloads([]);
    setSlices(null);
    setGcode(null);
    setToolpath(null);
    setSupportModifiers([]);
    setSupportPaintMode(null);
    setProcessPaintActive(false);
    setProcessModifiers([]);
    setMouseEarPoints([]);
    setMouseEarPlacement("auto");
    setModelSize(null);
    setDispatch(null);
    setPrinterState(null);
    setCameraUrl(null);
  }, [projectId]);

  useEffect(() => {
    const project = projects.find((item) => item.id === projectId);
    setVersionId(project?.head_version_id ?? null);
  }, [projectId, projects]);

  useEffect(() => {
    if (!client || !projectId) {
      setModelUrl(null);
      return;
    }
    let cancelled = false;
    void client
      .getProject(projectId)
      .then(async (project) => {
        const version = project.head_version;
        const painted = version?.assets.find((asset) => asset.role === "preview");
        const shown = painted ?? version?.assets.find((asset) => asset.role === "model");
        if (!shown) return null;
        const download = await client.download(shown.asset_id);
        return { url: download.url, format: painted ? ("glb" as const) : ("stl" as const) };
      })
      .then((model) => {
        if (cancelled) return;
        setModelUrl(model?.url ?? null);
        setModelFormat(model?.format ?? "stl");
      })
      .catch(() => {
        if (!cancelled) setModelUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [client, projectId, versionId]);

  useEffect(() => {
    setNesting(null);
    setSlices(null);
    setGcode(null);
    setToolpath(null);
    setDispatch(null);
    setPrinterState(null);
    setCameraUrl(null);
    setProcessModifiers([]);
    setProcessMaterialSlot("inherit");
  }, [printerId]);

  useEffect(() => {
    if (!client || !gcode?.profileId || !dispatch) return;
    let active = true;
    const update = async () => {
      try {
        const next = await client.getPrinterState(gcode.profileId!);
        if (active) setPrinterState(next);
      } catch {
        // The explicit refresh button reports errors; background polling stays quiet.
      }
    };
    void update();
    const timer = window.setInterval(() => void update(), 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [client, dispatch, gcode?.profileId]);

  useEffect(() => () => {
    if (cameraUrl) URL.revokeObjectURL(cameraUrl);
  }, [cameraUrl]);

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

  async function planFarmBatch() {
    if (!client || !session) return;
    const items = projects.flatMap((project) => {
      const quantity = batchQuantities[project.id] ?? 0;
      return project.head_version_id && quantity > 0
        ? [{ version_id: project.head_version_id, quantity }]
        : [];
    });
    if (items.length === 0 || batchPrinterIds.length === 0) return;
    setError(null);
    setBusy("Планируем партию");
    try {
      setBatchPlan(await client.planPrintFarm({
        workspace_id: session.workspaceId,
        items,
        printer_profile_ids: batchPrinterIds,
        material_id: batchMaterialId,
        infill_density_pct: infillPct,
        wall_count: wallCount,
        margin_mm: bedMarginMm,
        gap_mm: partGapMm,
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
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
    setNesting(null);
    try {
      const accepted = await client.splitModel(versionId, {
        fit_bed: mode === "fit",
        printer_profile_id: mode === "fit" ? printerId || null : null,
        parts: mode === "fit" ? null : 2,
        margin_mm: bedMarginMm,
        gap_mm: partGapMm,
        repair: true,
        preview: false,
      });
      const job = await track(mode === "fit" ? "Режем под стол принтера" : "Режем пополам", accepted.job_id);
      if (job.status !== "succeeded") throw new Error((job.error as { message?: string })?.message ?? "не удалось разрезать");
      const result = job.result as NestingResult & { version_id?: string };
      setNesting({ ...result, parts: result.parts ?? [] });
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

  async function buildGcode() {
    if (!client || !versionId) return;
    setError(null);
    setGcode(null);
    setDispatch(null);
    setPrinterState(null);
    setCameraUrl(null);
    try {
      const accepted = await client.sliceModel(versionId, {
        printer_profile_id: printerId || null,
        material_id: materialId,
        infill_density_pct: infillPct,
        infill_pattern: infillPattern,
        wall_count: wallCount,
        top_solid_layers: topSolidLayers,
        bottom_solid_layers: bottomSolidLayers,
        adaptive_layer_height: adaptiveLayerHeight,
        min_layer_height_mm: adaptiveLayerHeight ? minLayerHeight : null,
        max_layer_height_mm: adaptiveLayerHeight ? maxLayerHeight : null,
        supports,
        support_type: supportType,
        support_modifiers: supportModifiers,
        process_modifiers: processModifiers,
        adhesion_mode: adhesionMode,
        brim_width_mm: brimWidthMm,
        mouse_ear_diameter_mm: mouseEarDiameterMm,
        mouse_ear_points_mm:
          adhesionMode === "mouse_ears" && mouseEarPlacement === "manual"
            ? mouseEarPoints
            : [],
        adhesion_speed_pct: adhesionSpeedPct,
        raft_margin_mm: raftMarginMm,
        raft_base_layers: raftBaseLayers,
        raft_interface_layers: raftInterfaceLayers,
        raft_base_layer_height_mm: raftBaseLayerHeightMm,
        raft_interface_layer_height_mm: raftInterfaceLayerHeightMm,
        raft_base_speed_pct: raftBaseSpeedPct,
        raft_interface_speed_pct: raftInterfaceSpeedPct,
        raft_air_gap_mm: raftAirGapMm,
        skirt: true,
      });
      const job = await track("Строим G-code", accepted.job_id);
      if (job.status !== "succeeded") throw new Error((job.error as { message?: string })?.message ?? "не удалось построить G-code");
      const result = job.result as {
        asset_id: string;
        format: string;
        stats: SliceStats;
        material_id?: string;
        printer_profile_id?: string | null;
      };
      const download = await client.download(result.asset_id);
      let parsedToolpath: ToolpathPreview | null = null;
      try {
        const response = await fetch(download.url);
        if (!response.ok) throw new Error(`G-code download failed (${response.status})`);
        parsedToolpath = parseToolpath(await response.text());
      } catch {
        // The export remains downloadable even when a storage CORS policy blocks inline preview.
      }
      setDiagnosis(null);
      setSymptoms([]);
      setGcode({
        assetId: result.asset_id,
        format: result.format,
        stats: result.stats,
        url: download.url,
        materialId: result.material_id ?? "pla",
        profileId: result.printer_profile_id ?? null,
      });
      setToolpath(parsedToolpath);
      setToolpathIndex(0);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function sendToPrinter() {
    if (!client || !session || !gcode?.profileId) return;
    setError(null);
    setDispatch(null);
    setBusy(bridge?.test_mode ? "Проверяем отправку" : "Отправляем на принтер");
    try {
      setDispatch(
        await client.dispatchPrint(gcode.profileId, {
          workspace_id: session.workspaceId,
          asset_id: gcode.assetId,
          start: startImmediately,
        }),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function refreshPrinter() {
    if (!client || !gcode?.profileId) return;
    setError(null);
    setBusy("Обновляем состояние принтера");
    try {
      const [nextState, image] = await Promise.all([
        client.getPrinterState(gcode.profileId),
        client.getPrinterCamera(gcode.profileId),
      ]);
      setPrinterState(nextState);
      setCameraUrl(URL.createObjectURL(image));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  /** F-056: the outcome goes back to the printer's profile; the next G-code prints with it. */
  async function reportPrint() {
    if (!client || !gcode?.profileId || !session) return;
    setError(null);
    setPhotoFindings(null);
    try {
      if (printPhotos.length > 0) {
        // F-056: the photos go to a vision model; what it sees joins what was ticked
        const ids: string[] = [];
        for (const [index, file] of printPhotos.entries()) {
          const asset = await client.uploadFile(session.workspaceId, await shrinkPhoto(file), `print-${index + 1}.jpg`, "image/jpeg");
          ids.push(asset.id);
        }
        const accepted = await client.reportPrintPhotos(gcode.profileId, {
          material_id: gcode.materialId,
          outcome,
          symptoms: outcome === "success" ? [] : symptoms,
          apply: true,
          photo_asset_ids: ids,
        });
        const job = await track("ИИ смотрит на фото", accepted.job_id);
        if (job.status !== "succeeded") throw new Error((job.error as { message?: string })?.message ?? "не удалось разобрать фото");
        const result = job.result as unknown as PrintDiagnosis & { photo: { seen: { symptom: string; evidence: string; confidence: number }[] } };
        setDiagnosis(result);
        setPhotoFindings(result.photo.seen.filter((item) => item.confidence >= 0.5));
        setPrintPhotos([]);
        return;
      }
      setDiagnosis(
        await client.reportPrint(gcode.profileId, {
          material_id: gcode.materialId,
          outcome,
          symptoms: outcome === "success" ? [] : symptoms,
          apply: true,
        }),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  if (!ready) return <LoadingScreen />;
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
  const selectedPrinter = printers.find((profile) => profile.id === printerId);
  const selectedRaftDensity = selectedPrinter?.raft_density_profiles[materialId];
  const loadedMaterialSlots = selectedPrinter?.material_slots ?? [];

  return (
    <div className="stack">
      <div>
        <h2 style={{ margin: 0 }}>Слайсер</h2>
        <p className="muted" style={{ margin: "6px 0 0" }}>
          Подготовка модели к печати по порядку: проверка → ориентация → нарезка на части под стол →
          файл для принтера (3MF/STL для внешнего слайсера, либо готовый G-code от нашего собственного —
          с периметрами, заполнением и поддержками).
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
        <label className="stack" style={{ minWidth: 180 }}>
          <span className="muted">Материал</span>
          <select className="input" value={materialId} onChange={(event) => setMaterialId(event.target.value)}>
            {materials.map((material) => <option key={material.id} value={material.id}>{material.name}</option>)}
          </select>
        </label>
        <span className="muted">
          Рафт: основа {selectedRaftDensity?.base_density_pct ?? 40}% · интерфейс{" "}
          {selectedRaftDensity?.interface_density_pct ?? 100}% ·{" "}
          {selectedRaftDensity ? "профиль пары" : "fallback"}
        </span>
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

      <section className="card stack" aria-label="Планирование партии для фермы">
        <div>
          <strong>Партия для нескольких принтеров</strong>
          <div className="muted">
            Выберите модели, тираж и доступные машины. Планировщик распределит копии по
            платформам с учётом размеров столов, материала, заполнения и стенок. Это план —
            физическая отправка на принтеры выполняется отдельно после подготовки G-code.
          </div>
        </div>
        <div className="grid">
          <div className="stack">
            <strong>Модели и тираж</strong>
            {projects.map((candidate) => (
              <label key={candidate.id} className="row" style={{ justifyContent: "space-between" }}>
                <span>{candidate.name}</span>
                <input
                  className="input"
                  style={{ width: 88 }}
                  type="number"
                  min={0}
                  max={50}
                  value={batchQuantities[candidate.id] ?? 0}
                  aria-label={`Тираж ${candidate.name}`}
                  onChange={(event) => {
                    const quantity = Math.max(0, Math.min(50, Number(event.target.value) || 0));
                    setBatchQuantities((current) => ({ ...current, [candidate.id]: quantity }));
                    setBatchPlan(null);
                  }}
                />
              </label>
            ))}
          </div>
          <div className="stack">
            <strong>Доступные принтеры</strong>
            {printers.map((profile) => (
              <label key={profile.id} className="row">
                <input
                  type="checkbox"
                  checked={batchPrinterIds.includes(profile.id)}
                  onChange={(event) => {
                    setBatchPrinterIds((current) => event.target.checked
                      ? [...current, profile.id]
                      : current.filter((id) => id !== profile.id));
                    setBatchPlan(null);
                  }}
                />
                <span>{profile.name}</span>
              </label>
            ))}
            <label className="stack">
              <span className="muted">Материал</span>
              <select
                className="input"
                value={batchMaterialId}
                onChange={(event) => {
                  setBatchMaterialId(event.target.value);
                  setBatchPlan(null);
                }}
              >
                {materials.map((material) => (
                  <option key={material.id} value={material.id}>{material.name}</option>
                ))}
              </select>
            </label>
          </div>
        </div>
        <div className="muted">
          Заполнение {infillPct}% · стенок {wallCount} · до края {bedMarginMm} мм · между деталями {partGapMm} мм
        </div>
        <button
          className="btn primary"
          disabled={
            !!busy
            || batchPrinterIds.length === 0
            || !Object.values(batchQuantities).some((quantity) => quantity > 0)
          }
          onClick={() => void planFarmBatch()}
        >
          Рассчитать партию
        </button>
        {batchPlan && (
          <div className="stack">
            <div className="row" style={{ flexWrap: "wrap" }}>
              <span className="chip">{batchPlan.item_count} шт.</span>
              <span className="chip">{batchPlan.plate_count} платформ</span>
              <span className="chip">~{Math.ceil(batchPlan.estimated_makespan_minutes / 60)} ч до завершения</span>
              <span className="chip">{batchPlan.estimated_material_g.toFixed(1)} г</span>
              <span className="chip">{batchPlan.estimated_material_cost.toFixed(2)} {batchPlan.currency}</span>
            </div>
            {batchPlan.assignments.map((assignment) => (
              <div key={assignment.printer_profile_id} className="card stack">
                <strong>{assignment.printer_name} · {assignment.plates.length} платформ</strong>
                <span className="muted">
                  Стол {assignment.bed_mm.map((value) => Math.round(value)).join(" × ")} мм · ~{Math.ceil(assignment.estimated_minutes / 60)} ч
                </span>
                {assignment.plates.map((plate) => (
                  <div key={plate.number}>
                    <strong>Платформа {plate.number}</strong>
                    <ul className="list">
                      {plate.placements.map((placement) => (
                        <li key={`${placement.version_id}-${placement.copy_number}`}>
                          {placement.project_name} · копия {placement.copy_number} · X {placement.plate_offset_mm[0].toFixed(1)} · Y {placement.plate_offset_mm[1].toFixed(1)} · {placement.plate_rotation_deg}°
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </section>

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
            Модель больше стола — режем плоскостями на отдельные STL и автоматически раскладываем их на столе с поворотом 0/90°.
          </span>
          <div className="row" style={{ flexWrap: "wrap", alignItems: "end" }}>
            <label className="stack" style={{ minWidth: 150 }}>
              <span className="muted">До края стола, мм</span>
              <input
                className="input"
                type="number"
                min={0}
                max={50}
                step={1}
                value={bedMarginMm}
                onChange={(event) => setBedMarginMm(Math.max(0, Math.min(50, Number(event.target.value) || 0)))}
              />
            </label>
            <label className="stack" style={{ minWidth: 150 }}>
              <span className="muted">Между деталями, мм</span>
              <input
                className="input"
                type="number"
                min={0}
                max={50}
                step={1}
                value={partGapMm}
                onChange={(event) => setPartGapMm(Math.max(0, Math.min(50, Number(event.target.value) || 0)))}
              />
            </label>
          </div>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <button className="btn" disabled={!versionId || !!busy || !printerId} onClick={() => void cut("fit")}>
              Под стол принтера
            </button>
            <button className="btn" disabled={!versionId || !!busy} onClick={() => void cut("half")}>
              Пополам
            </button>
          </div>
          {nesting && (
            <>
              <ul className="list">
                {nesting.parts.map((part) => (
                  <li key={part.name}>
                    <strong>{part.name}</strong>{" "}
                    <span className="muted mono">{part.extents_mm.map((v) => v.toFixed(0)).join(" × ")} мм</span>
                    {part.plate_offset_mm && (
                      <span className="muted">
                        {" "}· X {part.plate_offset_mm[0].toFixed(1)} · Y {part.plate_offset_mm[1].toFixed(1)} · {part.plate_rotation_deg ?? 0}°
                      </span>
                    )}
                    {part.fits_bed === false && <span className="status-yellow"> · не влезает</span>}
                  </li>
                ))}
              </ul>
              <BedNestingPreview result={nesting} />
            </>
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
          <span className="muted">Сечения реальной геометрии с высотой слоя выбранного принтера — предпросмотр контуров без периметров и заполнения (для этого см. шаг 6).</span>
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

        <div className="card stack">
          <strong>6 · G-code для принтера</strong>
          <span className="muted">
            Периметры, заполнение и (при необходимости) поддержки — построенные по-настоящему,
            слой за слоем, а не просто эскиз сечения.
          </span>
          <label className="stack">
            <span className="muted">Заполнение: {infillPct}%</span>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={infillPct}
              onChange={(event) => setInfillPct(Number(event.target.value))}
              aria-label="Плотность заполнения"
            />
          </label>
          <div className="row">
            <span className="muted">Узор:</span>
            <button
              type="button"
              className={`chip ${infillPattern === "lines" ? "selected" : ""}`}
              onClick={() => setInfillPattern("lines")}
              title="Прямые линии, направление чередуется через слой"
            >
              Линии
            </button>
            <button
              type="button"
              className={`chip ${infillPattern === "honeycomb" ? "selected" : ""}`}
              onClick={() => setInfillPattern("honeycomb")}
              title="Настоящая шестигранная сетка (соты)"
            >
              Соты
            </button>
          </div>
          <label className="stack">
            <span className="muted">Стенок: {wallCount}</span>
            <input
              type="range"
              min={1}
              max={6}
              value={wallCount}
              onChange={(event) => setWallCount(Number(event.target.value))}
              aria-label="Количество стенок"
            />
          </label>
          <div className="row" style={{ alignItems: "end", gap: 12, flexWrap: "wrap" }}>
            <label className="stack" style={{ minWidth: 150 }}>
              <span className="muted">Сплошных верхних слоёв</span>
              <input
                type="number"
                min={0}
                max={20}
                value={topSolidLayers}
                onChange={(event) =>
                  setTopSolidLayers(Math.max(0, Math.min(20, Number(event.target.value) || 0)))
                }
                aria-label="Сплошные верхние слои"
              />
            </label>
            <label className="stack" style={{ minWidth: 150 }}>
              <span className="muted">Сплошных нижних слоёв</span>
              <input
                type="number"
                min={0}
                max={20}
                value={bottomSolidLayers}
                onChange={(event) =>
                  setBottomSolidLayers(Math.max(0, Math.min(20, Number(event.target.value) || 0)))
                }
                aria-label="Сплошные нижние слои"
              />
            </label>
          </div>
          <span className="muted">Закрывают верх, низ, промежуточные ступени и нависающие площадки.</span>
          <label className="row" style={{ alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={adaptiveLayerHeight}
              onChange={(event) => setAdaptiveLayerHeight(event.target.checked)}
            />
            <span className="muted">Адаптивная высота слоя по геометрии</span>
          </label>
          <div className="row" style={{ alignItems: "end", gap: 12, flexWrap: "wrap" }}>
            <label className="stack" style={{ minWidth: 150 }}>
              <span className="muted">Минимальный слой, мм</span>
              <input
                type="number"
                min={0.04}
                max={1}
                step={0.01}
                value={minLayerHeight}
                disabled={!adaptiveLayerHeight}
                onChange={(event) => {
                  const value = Number(event.target.value) || 0.04;
                  setMinLayerHeight(Math.max(0.04, Math.min(maxLayerHeight, value)));
                }}
                aria-label="Минимальная высота адаптивного слоя"
              />
            </label>
            <label className="stack" style={{ minWidth: 150 }}>
              <span className="muted">Максимальный слой, мм</span>
              <input
                type="number"
                min={0.04}
                max={1}
                step={0.01}
                value={maxLayerHeight}
                disabled={!adaptiveLayerHeight}
                onChange={(event) => {
                  const value = Number(event.target.value) || minLayerHeight;
                  setMaxLayerHeight(Math.min(1, Math.max(minLayerHeight, value)));
                }}
                aria-label="Максимальная высота адаптивного слоя"
              />
            </label>
          </div>
          <span className="muted">
            На наклонных и горизонтальных деталях слой тоньше, на вертикальных стенках — толще.
          </span>
          <div className="stack">
            <span className="muted">Сцепление с печатным столом</span>
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              {([
                ["auto", "Авто"],
                ["skirt", "Юбка"],
                ["brim", "Кайма"],
                ["mouse_ears", "Ушки"],
                ["raft", "Рафт"],
                ["none", "Без неё"],
              ] as const).map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  className={`chip ${adhesionMode === mode ? "selected" : ""}`}
                  onClick={() => setAdhesionMode(mode)}
                  aria-pressed={adhesionMode === mode}
                >
                  {label}
                </button>
              ))}
            </div>
            <label className="stack" style={{ maxWidth: 320 }}>
              <span className="muted">Ширина каймы: {brimWidthMm} мм</span>
              <input
                type="range"
                min={1}
                max={15}
                step={1}
                value={brimWidthMm}
                disabled={adhesionMode !== "brim"}
                onChange={(event) => setBrimWidthMm(Number(event.target.value))}
                aria-label="Ширина каймы"
              />
            </label>
            <label className="stack" style={{ maxWidth: 320 }}>
              <span className="muted">Скорость адгезии: {adhesionSpeedPct}%</span>
              <input
                type="range"
                min={20}
                max={100}
                step={5}
                value={adhesionSpeedPct}
                disabled={adhesionMode === "none"}
                onChange={(event) => setAdhesionSpeedPct(Number(event.target.value))}
                aria-label="Скорость адгезии"
              />
            </label>
            <label className="stack" style={{ maxWidth: 320 }}>
              <span className="muted">Поле рафта: {raftMarginMm} мм</span>
              <input
                type="range"
                min={3}
                max={15}
                step={1}
                value={raftMarginMm}
                disabled={adhesionMode !== "raft"}
                onChange={(event) => setRaftMarginMm(Number(event.target.value))}
                aria-label="Поле рафта"
              />
            </label>
            <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
              <label className="stack" style={{ maxWidth: 150 }}>
                <span className="muted">Слоёв основы</span>
                <input
                  type="number"
                  min={1}
                  max={3}
                  value={raftBaseLayers}
                  disabled={adhesionMode !== "raft"}
                  onChange={(event) =>
                    setRaftBaseLayers(Math.min(3, Math.max(1, Number(event.target.value) || 1)))
                  }
                  aria-label="Слои основы рафта"
                />
              </label>
              <label className="stack" style={{ maxWidth: 180 }}>
                <span className="muted">Высота основы, мм</span>
                <input
                  type="number"
                  min={0.04}
                  max={1}
                  step={0.01}
                  value={raftBaseLayerHeightMm ?? ""}
                  placeholder="Профиль"
                  disabled={adhesionMode !== "raft"}
                  onChange={(event) =>
                    setRaftBaseLayerHeightMm(
                      event.target.value === "" ? null : Number(event.target.value),
                    )
                  }
                  aria-label="Высота слоя основы рафта"
                />
              </label>
              <label className="stack" style={{ maxWidth: 180 }}>
                <span className="muted">Скорость основы: {raftBaseSpeedPct}%</span>
                <input
                  type="range"
                  min={20}
                  max={100}
                  step={5}
                  value={raftBaseSpeedPct}
                  disabled={adhesionMode !== "raft"}
                  onChange={(event) => setRaftBaseSpeedPct(Number(event.target.value))}
                  aria-label="Скорость основы рафта"
                />
              </label>
              <label className="stack" style={{ maxWidth: 180 }}>
                <span className="muted">Высота интерфейса, мм</span>
                <input
                  type="number"
                  min={0.04}
                  max={1}
                  step={0.01}
                  value={raftInterfaceLayerHeightMm ?? ""}
                  placeholder="Профиль"
                  disabled={adhesionMode !== "raft"}
                  onChange={(event) =>
                    setRaftInterfaceLayerHeightMm(
                      event.target.value === "" ? null : Number(event.target.value),
                    )
                  }
                  aria-label="Высота слоя интерфейса рафта"
                />
              </label>
              <label className="stack" style={{ maxWidth: 180 }}>
                <span className="muted">Скорость интерфейса: {raftInterfaceSpeedPct}%</span>
                <input
                  type="range"
                  min={20}
                  max={100}
                  step={5}
                  value={raftInterfaceSpeedPct}
                  disabled={adhesionMode !== "raft"}
                  onChange={(event) => setRaftInterfaceSpeedPct(Number(event.target.value))}
                  aria-label="Скорость интерфейса рафта"
                />
              </label>
              <label className="stack" style={{ maxWidth: 150 }}>
                <span className="muted">Слоёв интерфейса</span>
                <input
                  type="number"
                  min={1}
                  max={3}
                  value={raftInterfaceLayers}
                  disabled={adhesionMode !== "raft"}
                  onChange={(event) =>
                    setRaftInterfaceLayers(
                      Math.min(3, Math.max(1, Number(event.target.value) || 1)),
                    )
                  }
                  aria-label="Слои интерфейса рафта"
                />
              </label>
              <label className="stack" style={{ maxWidth: 150 }}>
                <span className="muted">Z-зазор, мм</span>
                <input
                  type="number"
                  min={0.05}
                  max={0.5}
                  step={0.05}
                  value={raftAirGapMm}
                  disabled={adhesionMode !== "raft"}
                  onChange={(event) =>
                    setRaftAirGapMm(
                      Math.min(0.5, Math.max(0.05, Number(event.target.value) || 0.15)),
                    )
                  }
                  aria-label="Воздушный зазор рафта"
                />
              </label>
            </div>
            <label className="stack" style={{ maxWidth: 320 }}>
              <span className="muted">Диаметр ушек: {mouseEarDiameterMm} мм</span>
              <input
                type="range"
                min={5}
                max={30}
                step={1}
                value={mouseEarDiameterMm}
                disabled={adhesionMode !== "mouse_ears"}
                onChange={(event) => setMouseEarDiameterMm(Number(event.target.value))}
                aria-label="Диаметр мышиных ушек"
              />
            </label>
            <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <span className="muted">Позиции ушек:</span>
              <button
                type="button"
                className={`chip ${mouseEarPlacement === "auto" ? "selected" : ""}`}
                disabled={adhesionMode !== "mouse_ears"}
                onClick={() => setMouseEarPlacement("auto")}
              >
                Авто по углам
              </button>
              <button
                type="button"
                className={`chip ${mouseEarPlacement === "manual" ? "selected" : ""}`}
                disabled={adhesionMode !== "mouse_ears"}
                onClick={() => {
                  setMouseEarPlacement("manual");
                  setSupportPaintMode(null);
                }}
              >
                Расставить на модели
              </button>
              {adhesionMode === "mouse_ears" && mouseEarPlacement === "manual" && (
                <>
                  <span className="muted">Точек: {mouseEarPoints.length}/32</span>
                  <button
                    type="button"
                    className="chip"
                    disabled={!mouseEarPoints.length}
                    onClick={() => setMouseEarPoints((points) => points.slice(0, -1))}
                  >
                    Отменить точку
                  </button>
                  <button
                    type="button"
                    className="chip"
                    disabled={!mouseEarPoints.length}
                    onClick={() => setMouseEarPoints([])}
                  >
                    Очистить точки
                  </button>
                </>
              )}
            </div>
            <span className="muted">
              Авто применяет коррекцию по прошлым отчётам печати; ручной выбор всегда имеет
              приоритет. Скорость адгезии применяется к юбке, кайме и ушкам; для рафта она
              остаётся безопасной базой, а основа и интерфейс имеют отдельные множители. Пустая
              высота наследует слой принтера; явная высота ограничена соплом. Рафт разделяет
              настраиваемые слои основы и интерфейса отделяемым Z-зазором от модели. В
              ручном режиме нажмите на внешний край модели ниже: точка сохраняется в координатах
              модели и переносится вместе с поворотом и центрированием на столе.
            </span>
          </div>
          <label className="row" style={{ alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={supports}
              onChange={(event) => {
                setSupports(event.target.checked);
                if (!event.target.checked) {
                  setSupportModifiers([]);
                  setSupportPaintMode(null);
                }
              }}
            />
            <span className="muted">Поддержки под нависаниями</span>
          </label>
          <div className="row">
            <span className="muted">Тип поддержек:</span>
            <button
              type="button"
              className={`chip ${supportType === "grid" ? "selected" : ""}`}
              onClick={() => setSupportType("grid")}
              disabled={!supports}
              title="Вертикальные колонны по сетке"
            >
              Сетка
            </button>
            <button
              type="button"
              className={`chip ${supportType === "tree" ? "selected" : ""}`}
              onClick={() => setSupportType("tree")}
              disabled={!supports}
              title="Наклонные ветви сливаются в общие стволы и тратят меньше пластика"
            >
              Дерево
            </button>
          </div>
          <div className="stack support-paint">
            <div className="row" style={{ alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span className="muted">Нарисовать на модели:</span>
              <button
                type="button"
                className={`chip ${supportPaintMode === "block" ? "selected" : ""}`}
                onClick={() => {
                  setSupports(true);
                  setProcessPaintActive(false);
                  setSupportPaintMode((mode) => (mode === "block" ? null : "block"));
                }}
              >
                Blocker
              </button>
              <button
                type="button"
                className={`chip ${supportPaintMode === "enforce" ? "selected" : ""}`}
                onClick={() => {
                  setSupports(true);
                  setProcessPaintActive(false);
                  setSupportPaintMode((mode) => (mode === "enforce" ? null : "enforce"));
                }}
              >
                Enforcer
              </button>
              <label className="row" style={{ alignItems: "center", gap: 6 }}>
                <span className="muted">Кисть {supportBrushMm} мм</span>
                <input
                  type="range"
                  min={2}
                  max={40}
                  step={2}
                  value={supportBrushMm}
                  onChange={(event) => setSupportBrushMm(Number(event.target.value))}
                  aria-label="Ширина кисти локальных областей"
                />
              </label>
            </div>
            <span className="muted">
              Blocker запрещает автоматическую поддержку, Enforcer требует её даже на более
              пологой нижней поверхности. Последний штрих в области имеет приоритет.
            </span>
            <div className="row" style={{ alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                className={`chip ${processPaintActive ? "selected" : ""}`}
                onClick={() => {
                  setSupportPaintMode(null);
                  setProcessPaintActive((active) => !active);
                }}
              >
                Локальная плотность
              </button>
              <label className="row" style={{ alignItems: "center", gap: 6 }}>
                <span className="muted">{processDensityPct}%</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={5}
                  value={processDensityPct}
                  disabled={!processPaintActive}
                  onChange={(event) => setProcessDensityPct(Number(event.target.value))}
                  aria-label="Локальная плотность заполнения"
                />
              </label>
              <label className="row" style={{ alignItems: "center", gap: 6 }}>
                <span className="muted">Скорость {processSpeedPct}%</span>
                <input
                  type="range"
                  min={20}
                  max={200}
                  step={5}
                  value={processSpeedPct}
                  disabled={!processPaintActive}
                  onChange={(event) => setProcessSpeedPct(Number(event.target.value))}
                  aria-label="Локальная скорость печати"
                />
              </label>
              <label className="row" style={{ alignItems: "center", gap: 6 }}>
                <span className="muted">
                  Сопло {processTemperatureOffsetC > 0 ? "+" : ""}{processTemperatureOffsetC}°C
                </span>
                <input
                  type="range"
                  min={-20}
                  max={20}
                  step={5}
                  value={processTemperatureOffsetC}
                  disabled={!processPaintActive}
                  onChange={(event) => setProcessTemperatureOffsetC(Number(event.target.value))}
                  aria-label="Локальное смещение температуры сопла"
                />
              </label>
              <label className="row" style={{ alignItems: "center", gap: 6 }}>
                <span className="muted">Рисунок</span>
                <select
                  value={processInfillPattern}
                  disabled={!processPaintActive}
                  onChange={(event) =>
                    setProcessInfillPattern(
                      event.target.value as "inherit" | "lines" | "honeycomb",
                    )
                  }
                  aria-label="Локальный рисунок заполнения"
                >
                  <option value="inherit">Как у модели</option>
                  <option value="lines">Линии</option>
                  <option value="honeycomb">Соты</option>
                </select>
              </label>
              <label className="row" style={{ alignItems: "center", gap: 6 }}>
                <span className="muted">Стенки</span>
                <select
                  value={processWallCount}
                  disabled={!processPaintActive}
                  onChange={(event) =>
                    setProcessWallCount(
                      event.target.value === "inherit" ? "inherit" : Number(event.target.value),
                    )
                  }
                  aria-label="Локальное число стенок"
                >
                  <option value="inherit">Как у модели</option>
                  {[1, 2, 3, 4, 5, 6].map((count) => (
                    <option key={count} value={count}>{count}</option>
                  ))}
                </select>
              </label>
              <label className="row" style={{ alignItems: "center", gap: 6 }}>
                <span className="muted">Материал</span>
                <select
                  value={processMaterialSlot}
                  disabled={!processPaintActive}
                  onChange={(event) =>
                    setProcessMaterialSlot(
                      event.target.value === "inherit" ? "inherit" : Number(event.target.value),
                    )
                  }
                  aria-label="Локальный слот материала"
                >
                  <option value="inherit">Основной материал</option>
                  {loadedMaterialSlots.map((slot) => (
                    <option key={slot.slot} value={slot.slot}>
                      Слот {slot.slot + 1} ·{" "}
                      {materials.find((item) => item.id === slot.material_id)?.name ?? slot.material_id}
                    </option>
                  ))}
                </select>
              </label>
              <span className="muted">Областей: {processModifiers.length}/64</span>
              <button
                type="button"
                className="chip"
                disabled={!processModifiers.length}
                onClick={() => setProcessModifiers((current) => current.slice(0, -1))}
              >
                Отменить область
              </button>
              <button
                type="button"
                className="chip"
                disabled={!processModifiers.length}
                onClick={() => setProcessModifiers([])}
              >
                Очистить области
              </button>
            </div>
            <span className="muted">
              Нарисуйте область на горизонтальной грани: плотность и рисунок меняют разреженное
              заполнение, число стенок — периметры, а скорость — sparse infill, периметры,
              сплошные верх/низ и support внутри области. Смещение сопла задаёт целевую команду
              M104 без ожидания и затем возвращает базовую цель. Назначение материала фиксируется
              в задании по загруженному слоту, но текущий G-code ещё не выдаёт Tn/purge. Последняя
              область имеет приоритет.
            </span>
            {modelUrl ? (
              <div className="support-paint-viewer">
                <ModelViewer
                  url={modelUrl}
                  format={modelFormat}
                  bodyId="body"
                  selected={[]}
                  onSelect={() => undefined}
                  onMeasure={setModelSize}
                  regionMode={supportPaintMode !== null || processPaintActive}
                  paintColour={
                    supportPaintMode === "block"
                      ? "#ff6b6b"
                      : supportPaintMode === "enforce"
                        ? "#58d6a9"
                        : processPaintActive
                          ? "#a985ff"
                          : null
                  }
                  brushMm={supportBrushMm}
                  onRegion={(selection) => {
                    if (!selection) return;
                    if (supportPaintMode) {
                      setSupportModifiers((current) => [
                        ...current,
                        { mode: supportPaintMode, region: selection.region },
                      ].slice(-256));
                      return;
                    }
                    if (!processPaintActive) return;
                    if (selection.region.kind === "lasso" && selection.region.axis !== "z") {
                      setError("Локальную плотность рисуют на горизонтальной грани модели");
                      return;
                    }
                    setProcessModifiers((current) => [
                      ...current,
                      {
                        infill_density_pct: processDensityPct,
                        print_speed_pct: processSpeedPct,
                        nozzle_temperature_offset_c: processTemperatureOffsetC,
                        infill_pattern:
                          processInfillPattern === "inherit" ? null : processInfillPattern,
                        wall_count:
                          processWallCount === "inherit" ? null : processWallCount,
                        material_slot:
                          processMaterialSlot === "inherit" ? null : processMaterialSlot,
                        region: selection.region,
                      },
                    ].slice(-64));
                  }}
                  onViewportPick={
                    adhesionMode === "mouse_ears" &&
                    mouseEarPlacement === "manual" &&
                    supportPaintMode === null &&
                    !processPaintActive
                      ? (hit) => {
                          if (mouseEarPoints.length >= 32) return;
                          setMouseEarPoints((points) => [
                            ...points,
                            [hit.point.x, hit.point.y, hit.point.z] as [number, number, number],
                          ].slice(-32));
                        }
                      : undefined
                  }
                  markers={mouseEarPoints.map((point, index) => ({
                    key: `mouse-ear-${index}`,
                    colour: "#ffb020",
                    point,
                    kind: "note" as const,
                  }))}
                  showGrid
                />
              </div>
            ) : (
              <span className="muted">3D-модель для рисования загружается…</span>
            )}
            <div className="row" style={{ alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span className="muted">
                Штрихов: {supportModifiers.length}
                {modelSize && ` · модель ${modelSize.x.toFixed(0)} × ${modelSize.y.toFixed(0)} × ${modelSize.z.toFixed(0)} мм`}
              </span>
              <button
                type="button"
                className="chip"
                disabled={!supportModifiers.length}
                onClick={() => setSupportModifiers((current) => current.slice(0, -1))}
              >
                Отменить последний
              </button>
              <button
                type="button"
                className="chip"
                disabled={!supportModifiers.length}
                onClick={() => setSupportModifiers([])}
              >
                Очистить
              </button>
            </div>
          </div>
          <button className="btn primary" disabled={!versionId || !!busy} onClick={() => void buildGcode()}>
            Построить G-code
          </button>
          {gcode && (
            <div className="stack">
              <div className="muted">
                {gcode.stats.total_layers} слоёв · {gcode.stats.filament_used_g.toFixed(1)} г филамента
                {gcode.stats.support_columns > 0 &&
                  (gcode.stats.support_type === "tree"
                    ? ` · ${gcode.stats.support_branches ?? 0} ветвей / ${gcode.stats.support_trunks ?? 0} стволов`
                    : ` · ${gcode.stats.support_columns} колонн поддержки`)}
                {" · ~"}
                {Math.max(1, Math.round(gcode.stats.estimated_time_s / 60))} мин печати
                {gcode.stats.travel_mm != null &&
                  ` · ${(gcode.stats.travel_mm / 1000).toFixed(1)} м холостого хода`}
                {(gcode.stats.solid_skin_paths ?? 0) > 0 &&
                  ` · ${gcode.stats.solid_skin_paths} линий сплошной оболочки`}
                {gcode.stats.layer_height_mode === "adaptive" &&
                  gcode.stats.min_layer_height_mm != null &&
                  gcode.stats.max_layer_height_mm != null &&
                  ` · адаптивный слой ${gcode.stats.min_layer_height_mm.toFixed(2)}–${gcode.stats.max_layer_height_mm.toFixed(2)} мм`}
                {(gcode.stats.support_modifiers ?? 0) > 0 &&
                  ` · ${gcode.stats.support_modifiers} штрихов поддержек (${gcode.stats.support_blocked_faces ?? 0} заблокировано / ${gcode.stats.support_enforced_faces ?? 0} добавлено граней)`}
                {(gcode.stats.process_modifiers ?? 0) > 0 &&
                  ` · локальная плотность: ${gcode.stats.process_modifiers} областей / ${gcode.stats.process_modified_layers ?? 0} слоёв`}
                {(gcode.stats.material_assigned_regions ?? 0) > 0 &&
                  ` · материал назначен ${gcode.stats.material_assigned_regions} областям (переключение инструмента ещё выключено)`}
                {gcode.stats.adhesion_mode &&
                  ` · адгезия: ${
                    gcode.stats.adhesion_mode === "brim"
                      ? `кайма ${gcode.stats.brim_width_mm ?? 0} мм`
                      : gcode.stats.adhesion_mode === "mouse_ears"
                        ? `${gcode.stats.mouse_ear_count ?? 0} ушек Ø${gcode.stats.mouse_ear_diameter_mm ?? 0} мм${(gcode.stats.mouse_ear_requested_count ?? 0) > 0 ? ` · отклонено ${gcode.stats.mouse_ear_rejected_count ?? 0}` : ""}`
                      : gcode.stats.adhesion_mode === "raft"
                        ? `рафт: ${gcode.stats.raft_layers ?? 0} сл. (${gcode.stats.raft_base_layers ?? 0}+${gcode.stats.raft_interface_layers ?? 0}), высота ${gcode.stats.raft_base_layer_height_mm ?? 0}/${gcode.stats.raft_interface_layer_height_mm ?? 0} мм, плотность ${gcode.stats.raft_base_density_pct ?? 40}%/${gcode.stats.raft_interface_density_pct ?? 100}% (${gcode.stats.raft_density_profiled ? "профиль пары" : "fallback"}), поле ${gcode.stats.raft_margin_mm ?? 0} мм, зазор ${gcode.stats.raft_air_gap_mm ?? 0} мм, скорость ${gcode.stats.adhesion_speed_pct ?? 100}% × ${gcode.stats.raft_base_speed_pct ?? 100}%/${gcode.stats.raft_interface_speed_pct ?? 100}%`
                      : gcode.stats.adhesion_mode === "skirt"
                        ? "юбка"
                        : "нет"
                  }`}
              </div>
              {(gcode.stats.xy_compensation_mm || gcode.stats.shrinkage_pct || (gcode.stats.flow_pct ?? 100) !== 100) ? (
                <div className="muted">
                  С калибровкой этого принтера: контур{" "}
                  {(-(gcode.stats.xy_compensation_mm ?? 0)).toFixed(2)} мм на сторону, усадка{" "}
                  {(gcode.stats.shrinkage_pct ?? 0).toFixed(1)}% учтена, поток{" "}
                  {(gcode.stats.flow_pct ?? 100).toFixed(1)}%
                </div>
              ) : (
                <div className="muted">
                  Калибровки принтера нет — размеры по модели. Напечатайте купон калибровки, чтобы
                  отверстия и посадки выходили точно.
                </div>
              )}
              {gcode.stats.tuning && Object.keys(gcode.stats.tuning).length > 0 && (
                <div className="muted">
                  С поправками прошлых печатей ({gcode.materialId.toUpperCase()}): {describeTuning(gcode.stats.tuning)}
                </div>
              )}
              <a href={gcode.url} target="_blank" rel="noopener noreferrer" className="muted mono">
                GCODE ↗
              </a>
              {toolpath?.layers.length ? (() => {
                const layer = toolpath.layers[Math.min(toolpathIndex, toolpath.layers.length - 1)];
                const [minX, minY] = toolpath.bounds.min;
                const [maxX, maxY] = toolpath.bounds.max;
                const width = Math.max(maxX - minX, 1);
                const depth = Math.max(maxY - minY, 1);
                return (
                  <div className="stack toolpath-preview">
                    <div className="row" style={{ justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                      <strong>Полный toolpath preview</strong>
                      <label className="row" style={{ alignItems: "center", gap: 6 }}>
                        <input
                          type="checkbox"
                          checked={showTravel}
                          onChange={(event) => setShowTravel(event.target.checked)}
                        />
                        <span className="muted">Холостые перемещения</span>
                      </label>
                    </div>
                    <svg
                      className="toolpath-preview-svg"
                      viewBox={`${minX - width * 0.02} ${-maxY - depth * 0.02} ${width * 1.04} ${depth * 1.04}`}
                      role="img"
                      aria-label={`Траектории слоя ${layer.index}`}
                    >
                      {TOOLPATH_LEGEND.map(([pathKind]) => {
                        if (pathKind === "travel" && !showTravel) return null;
                        const d = layer.segments
                          .filter((segment) => segment.kind === pathKind)
                          .map((segment) => `M ${segment.from[0]} ${-segment.from[1]} L ${segment.to[0]} ${-segment.to[1]}`)
                          .join(" ");
                        return d ? (
                          <path
                            key={pathKind}
                            d={d}
                            fill="none"
                            stroke={TOOLPATH_COLOURS[pathKind]}
                            strokeWidth={Math.max(width, depth) / (pathKind === "travel" ? 700 : 430)}
                            strokeOpacity={pathKind === "travel" ? 0.5 : 0.95}
                            vectorEffect="non-scaling-stroke"
                          />
                        ) : null;
                      })}
                    </svg>
                    <label className="stack">
                      <span>
                        Слой {layer.index} / {toolpath.layers.length} · Z {layer.z_mm.toFixed(3)} мм · {layer.segments.length} сегментов
                      </span>
                      <input
                        type="range"
                        min={0}
                        max={toolpath.layers.length - 1}
                        value={toolpathIndex}
                        onChange={(event) => setToolpathIndex(Number(event.target.value))}
                        aria-label="Выбрать слой траекторий"
                      />
                    </label>
                    <div className="toolpath-legend">
                      {TOOLPATH_LEGEND.map(([pathKind, label]) => (
                        <span key={pathKind} className="muted">
                          <i style={{ background: TOOLPATH_COLOURS[pathKind] }} /> {label}
                        </span>
                      ))}
                    </div>
                    <span className="muted">
                      Разобраны все {toolpath.layers.length} слоёв и {toolpath.segment_count} перемещений готового G-code; показывается выбранный слой.
                    </span>
                  </div>
                );
              })() : (
                <span className="muted">
                  Inline-preview недоступен, но G-code сохранён и доступен по ссылке выше.
                </span>
              )}
              <div className="stack" style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
                <div className="row" style={{ alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                  <div className="stack" style={{ gap: 3 }}>
                    <strong>{bridge?.test_mode ? "Тестовая отправка на принтер" : "Отправить на принтер"}</strong>
                    <span className="muted">
                      {bridge?.test_mode
                        ? "Проверим весь путь без подключения к реальному устройству."
                        : bridge?.enabled
                          ? "G-code загрузится в OctoPrint по защищённому серверному подключению."
                          : "Подключение к OctoPrint ещё не настроено на сервере."}
                    </span>
                  </div>
                  {bridge?.provider === "octoprint" && <span className="chip selected">OctoPrint</span>}
                  {bridge?.test_mode && <span className="chip">DEMO</span>}
                </div>
                <label className="row" style={{ alignItems: "center", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={startImmediately}
                    onChange={(event) => setStartImmediately(event.target.checked)}
                    disabled={!bridge?.enabled}
                  />
                  <span className="muted">Сразу начать печать после загрузки</span>
                </label>
                <button
                  className="btn primary"
                  type="button"
                  disabled={!!busy || !bridge?.enabled || !gcode.profileId}
                  onClick={() => void sendToPrinter()}
                >
                  {bridge?.test_mode
                    ? startImmediately
                      ? "Проверить загрузку и запуск"
                      : "Проверить загрузку"
                    : startImmediately
                      ? "Загрузить и печатать"
                      : "Загрузить в OctoPrint"}
                </button>
                {!gcode.profileId && (
                  <span className="muted">Выберите профиль принтера и постройте G-code заново.</span>
                )}
                {dispatch && (
                  <>
                    <div className="notice success" role="status">
                      {dispatch.provider === "stub"
                        ? "Тест пройден: файл принят, реальный принтер не использовался."
                        : dispatch.printing
                          ? "Файл загружен, печать запущена."
                          : "Файл загружен в OctoPrint и выбран для печати."}{" "}
                      <span className="mono">{dispatch.filename}</span>
                    </div>
                    <div className="stack" style={{ padding: 12, border: "1px solid var(--border)", borderRadius: 14 }}>
                      <div className="row" style={{ justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                        <strong>Принтер сейчас</strong>
                        <button className="btn" type="button" disabled={!!busy} onClick={() => void refreshPrinter()}>
                          Обновить + камера
                        </button>
                      </div>
                      {printerState ? (
                        <>
                          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                            <span className={`chip ${printerState.printing ? "selected" : ""}`}>{printerState.state}</span>
                            {printerState.filename && <span className="muted mono">{printerState.filename}</span>}
                          </div>
                          {printerState.completion_pct != null && printerState.printing && (
                            <label className="stack">
                              <span className="muted">Готово {printerState.completion_pct.toFixed(1)}%</span>
                              <progress max={100} value={printerState.completion_pct} style={{ width: "100%" }} />
                            </label>
                          )}
                          <span className="muted">
                            Сопло {printerState.nozzle_actual_c?.toFixed(0) ?? "—"}° / {printerState.nozzle_target_c?.toFixed(0) ?? "—"}° · Стол{" "}
                            {printerState.bed_actual_c?.toFixed(0) ?? "—"}° / {printerState.bed_target_c?.toFixed(0) ?? "—"}°
                            {printerState.remaining_seconds != null && ` · осталось ~${Math.ceil(printerState.remaining_seconds / 60)} мин`}
                          </span>
                        </>
                      ) : (
                        <span className="muted">Получаем состояние…</span>
                      )}
                      {cameraUrl && (
                        <img
                          src={cameraUrl}
                          alt="Камера принтера"
                          style={{ width: "100%", maxHeight: 360, objectFit: "cover", borderRadius: 12, background: "#0b1020" }}
                        />
                      )}
                    </div>
                  </>
                )}
              </div>
              <div className="stack" style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
                <strong>Как прошла печать?</strong>
                {!gcode.profileId ? (
                  <span className="muted">
                    Выберите профиль принтера выше и постройте G-code заново — поправки запоминаются для
                    конкретного принтера и материала.
                  </span>
                ) : (
                  <>
                    <div className="segmented compact">
                      {(
                        [
                          ["success", "Отлично"],
                          ["partial", "Есть дефекты"],
                          ["failed", "Не удалась"],
                        ] as const
                      ).map(([id, label]) => (
                        <button key={id} type="button" className={outcome === id ? "active" : ""} onClick={() => setOutcome(id)}>
                          {label}
                        </button>
                      ))}
                    </div>
                    {outcome !== "success" && (
                      <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
                        {SYMPTOMS.map(({ id, label }) => {
                          const on = symptoms.includes(id);
                          return (
                            <button
                              key={id}
                              type="button"
                              className={`chip${on ? " selected" : ""}`}
                              aria-pressed={on}
                              onClick={() =>
                                setSymptoms((current) => (on ? current.filter((s) => s !== id) : [...current, id]))
                              }
                            >
                              {label}
                            </button>
                          );
                        })}
                      </div>
                    )}
                    <label className="muted">
                      Фото печати — ИИ сам найдёт дефекты (нужен AI_PROVIDER=anthropic):{" "}
                      <input
                        type="file"
                        accept="image/jpeg,image/png"
                        multiple
                        onChange={(event) => setPrintPhotos(Array.from(event.target.files ?? []).slice(0, 3))}
                      />
                    </label>
                    <button
                      className="btn"
                      type="button"
                      disabled={!!busy || (outcome !== "success" && symptoms.length === 0 && printPhotos.length === 0)}
                      onClick={() => void reportPrint()}
                    >
                      {outcome === "success" ? "Запомнить, что всё хорошо" : "Разобрать и учесть в следующей печати"}
                    </button>
                  </>
                )}
                {photoFindings && (
                  <div className="muted">
                    {photoFindings.length === 0
                      ? "На фото ИИ дефектов не увидел."
                      : `ИИ увидел на фото: ${photoFindings.map((f) => `${SYMPTOMS.find((s) => s.id === f.symptom)?.label ?? f.symptom} (${f.evidence})`).join("; ")}.`}
                  </div>
                )}
                {diagnosis && (
                  <div className="stack">
                    {diagnosis.findings.map((finding) => (
                      <div key={finding.symptom} className="muted">
                        <strong>{SYMPTOMS.find((s) => s.id === finding.symptom)?.label}</strong>:{" "}
                        {SYMPTOM_HELP_RU[finding.symptom]?.causes ?? finding.causes.join("; ")}.{" "}
                        {finding.changes.length > 0
                          ? `Меняем: ${finding.changes
                              .map((c) => `${TUNING_LABELS[c.setting]?.[0] ?? c.setting} ${c.before} → ${c.after}`)
                              .join(", ")}. `
                          : "Настройки не меняем. "}
                        {SYMPTOM_HELP_RU[finding.symptom]?.advice ?? finding.advice}
                      </div>
                    ))}
                    <span className="muted">
                      {diagnosis.findings.length === 0
                        ? "Записано. "
                        : "Постройте G-code заново — он будет с этими поправками. "}
                      Отчётов по этому принтеру: {diagnosis.reports}.
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
