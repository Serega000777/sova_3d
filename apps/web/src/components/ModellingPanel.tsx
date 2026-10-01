"use client";

/**
 * Pro-mode panel for T-234: what to select (body, vertex, edge, face), the world grid with
 * snap and X/Y/Z symmetry, and an honest readout of the mesh's real topology.
 */
import {
  type ComponentKind,
  GRID_STEPS_MM,
  type ModellingGrid,
  type TopologyReport,
  topologyNotice,
} from "@physical-ai/contracts";

import type { ComponentSelectionInfo } from "@/components/ModelViewer";

const KINDS: { id: ComponentKind | null; en: string; ru: string }[] = [
  { id: null, en: "Body", ru: "Тело" },
  { id: "vertex", en: "Vertex", ru: "Вершина" },
  { id: "edge", en: "Edge", ru: "Ребро" },
  { id: "face", en: "Face", ru: "Грань" },
];

export function ModellingPanel({
  language,
  kind,
  onKind,
  boxSelect,
  onBoxSelect,
  selectThrough,
  onSelectThrough,
  grid,
  onGrid,
  report,
  selection,
  onClear,
}: {
  language: "en" | "ru";
  kind: ComponentKind | null;
  onKind: (kind: ComponentKind | null) => void;
  boxSelect: boolean;
  onBoxSelect: (value: boolean) => void;
  selectThrough: boolean;
  onSelectThrough: (value: boolean) => void;
  grid: ModellingGrid;
  onGrid: (grid: ModellingGrid) => void;
  report: TopologyReport | null;
  selection: ComponentSelectionInfo;
  onClear: () => void;
}) {
  const ru = language === "ru";
  const notice = report ? topologyNotice(report, language) : null;
  const unavailable = report?.status === "none";
  const size = selection.bounds
    ? selection.bounds.max.map((v, i) => v - (selection.bounds?.min[i] ?? 0))
    : null;
  return (
    <section className="modelling-panel" aria-label={ru ? "Сетка и компоненты" : "Grid and components"}>
      <div className="mp-row" role="group" aria-label={ru ? "Что выбирать" : "Select"}>
        {KINDS.map((item) => (
          <button
            key={item.id ?? "body"}
            type="button"
            className={kind === item.id ? "active" : ""}
            onClick={() => onKind(item.id)}
          >
            {ru ? item.ru : item.en}
          </button>
        ))}
      </div>
      {kind && (
        <div className="mp-row">
          <button type="button" className={boxSelect ? "active" : ""} onClick={() => onBoxSelect(!boxSelect)}>
            {ru ? "Рамка" : "Box"}
          </button>
          <button
            type="button"
            className={selectThrough ? "active" : ""}
            disabled={!boxSelect}
            onClick={() => onSelectThrough(!selectThrough)}
            title={ru ? "Выбирать и скрытое за поверхностью" : "Also select what is hidden behind the surface"}
          >
            {ru ? "Насквозь" : "Through"}
          </button>
          <button type="button" onClick={onClear} disabled={selection.count === 0}>
            {ru ? "Сбросить" : "Clear"}
          </button>
        </div>
      )}
      {kind && (
        <p className="mp-hint">
          {ru
            ? "Shift — добавить · Alt — убрать · Ctrl — переключить"
            : "Shift adds · Alt removes · Ctrl toggles"}
        </p>
      )}
      {report && report.status !== "none" && (
        <p className="mp-stats mono">
          {report.vertices.toLocaleString()} V · {report.edges.toLocaleString()} E · {report.faces.toLocaleString()} F
        </p>
      )}
      {kind && selection.count > 0 && (
        <p className="mp-stats mono">
          {ru ? "Выбрано" : "Selected"}: {selection.count} · {selection.vertices} V
          {size ? ` · ${size.map((v) => v.toFixed(2)).join(" × ")} mm` : ""}
        </p>
      )}
      {notice && <p className={`mp-notice ${unavailable ? "bad" : ""}`}>{notice}</p>}

      <div className="mp-row mp-grid">
        <label>
          {ru ? "Шаг" : "Step"}
          <select
            value={grid.step_mm}
            onChange={(e) => onGrid({ ...grid, step_mm: Number(e.target.value) })}
          >
            {[...new Set([...GRID_STEPS_MM, grid.step_mm])]
              .sort((a, b) => a - b)
              .map((step) => (
                <option key={step} value={step}>
                  {step} mm
                </option>
              ))}
          </select>
        </label>
        <button type="button" className={grid.snap ? "active" : ""} onClick={() => onGrid({ ...grid, snap: !grid.snap })}>
          {ru ? "Привязка" : "Snap"}
        </button>
      </div>
      <div className="mp-row" role="group" aria-label={ru ? "Симметрия" : "Symmetry"}>
        <span className="mp-label">{ru ? "Симметрия" : "Symmetry"}</span>
        {(["x", "y", "z"] as const).map((axis) => (
          <button
            key={axis}
            type="button"
            className={grid.symmetry[axis] ? "active" : ""}
            onClick={() => onGrid({ ...grid, symmetry: { ...grid.symmetry, [axis]: !grid.symmetry[axis] } })}
          >
            {axis.toUpperCase()}
          </button>
        ))}
      </div>
    </section>
  );
}
