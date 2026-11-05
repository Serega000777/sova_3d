"use client";

import type { SizeFamily } from "@physical-ai/contracts";
import { useEffect, useState } from "react";

import type { Size } from "./Inspector";
import {
  defaultSizeFamilyDraft,
  parseSizeFamilyDraft,
  type SizeFamilyDraft,
  type SizeFamilyLabel,
  type SizeFamilyPreset,
} from "../lib/size-family";

interface SizeFamilyCardProps {
  size: Size | null;
  family: SizeFamily | null;
  activeVersionId: string | null;
  headVersionId: string | null;
  loading: boolean;
  saving: boolean;
  canBuild: boolean;
  canSelect: boolean;
  language: "ru" | "en";
  onBuild: (presets: SizeFamilyPreset[]) => Promise<void>;
  onInspect: (versionId: string) => void;
  onSelect: (label: SizeFamilyLabel) => Promise<void>;
}

const LABELS = ["S", "M", "L"] as const;
const DIMENSIONS = ["width", "depth", "height"] as const;

export function SizeFamilyCard({
  size,
  family,
  activeVersionId,
  headVersionId,
  loading,
  saving,
  canBuild,
  canSelect,
  language,
  onBuild,
  onInspect,
  onSelect,
}: SizeFamilyCardProps) {
  const ru = language === "ru";
  const [draft, setDraft] = useState<SizeFamilyDraft | null>(null);
  const [validationError, setValidationError] = useState(false);

  useEffect(() => {
    setDraft(size ? defaultSizeFamilyDraft(size) : null);
    setValidationError(false);
  }, [size?.x, size?.y, size?.z]);

  function updateDraft(label: SizeFamilyLabel, dimension: (typeof DIMENSIONS)[number], value: string) {
    setDraft((current) => current
      ? { ...current, [label]: { ...current[label], [dimension]: value } }
      : current);
    setValidationError(false);
  }

  async function build() {
    if (!draft || saving || !canBuild) return;
    const presets = parseSizeFamilyDraft(draft);
    if (!presets) {
      setValidationError(true);
      return;
    }
    try {
      await onBuild(presets);
    } catch {
      // The page owns the shared error banner; keep the exact table available for retry.
    }
  }

  async function select(label: SizeFamilyLabel) {
    try {
      await onSelect(label);
    } catch {
      // The page owns the shared error banner.
    }
  }

  const dimensionLabel = (dimension: (typeof DIMENSIONS)[number]) =>
    dimension === "width"
      ? (ru ? "Ширина" : "Width")
      : dimension === "depth"
        ? (ru ? "Глубина" : "Depth")
        : (ru ? "Высота" : "Height");

  return (
    <div className="card stack" aria-label={ru ? "Семейство размеров S M L" : "S M L size family"}>
      <strong>{ru ? "Точное семейство S/M/L" : "Exact S/M/L family"}</strong>
      <span className="muted">
        {ru
          ? "Начальные ширины — 75/100/125%. Ширину, глубину и высоту каждой строки можно изменить независимо."
          : "Initial widths are 75/100/125%. Width, depth and height remain independently editable for every row."}
      </span>

      {canBuild && draft ? (
        <>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr><th style={{ textAlign: "left" }}>{ru ? "Размер" : "Size"}</th>{DIMENSIONS.map((dimension) => <th key={dimension} style={{ textAlign: "left" }}>{dimensionLabel(dimension)}, mm</th>)}</tr></thead>
              <tbody>
                {LABELS.map((label) => (
                  <tr key={label}>
                    <th style={{ textAlign: "left" }}>{label}</th>
                    {DIMENSIONS.map((dimension) => (
                      <td key={dimension} style={{ padding: "4px" }}>
                        <input className="input mono" aria-label={`${label} ${dimension} mm`} inputMode="decimal" value={draft[label][dimension]} disabled={saving} onChange={(event) => updateDraft(label, dimension, event.target.value)} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {validationError ? (
            <span className="status-yellow" role="alert">
              {ru
                ? "Для всех девяти полей нужны конечные числа в диапазоне (0, 10 000] мм. Допустима запятая или точка."
                : "All nine fields need finite values in (0, 10,000] mm. Either a comma or a dot is accepted."}
            </span>
          ) : null}
          <button className="btn primary" type="button" disabled={saving} onClick={() => void build()}>
            {saving ? (ru ? "Строим три размера…" : "Building three sizes…") : (ru ? "Создать семейство S/M/L" : "Build S/M/L family")}
          </button>
        </>
      ) : !canBuild ? (
        <span className="muted">
          {canSelect
            ? (ru ? "Для этой версии нельзя построить новое семейство; сохранённые размеры можно осмотреть или выбрать." : "A new family cannot be built from this version; saved sizes can still be inspected or selected.")
            : (ru ? "Сохранённые размеры можно осматривать; создавать семейство и менять голову проекта может редактор." : "Saved sizes can be inspected; an editor can build a family or change the project head.")}
        </span>
      ) : (
        <span className="muted">{ru ? "Откройте измеряемую модель." : "Open a measurable model first."}</span>
      )}

      {loading ? <span className="muted">{ru ? "Загружаем сохранённое семейство…" : "Loading saved family…"}</span> : null}
      {family ? (
        <div className="stack" aria-label={ru ? "Сохранённое семейство размеров" : "Saved size family"}>
          <strong>{ru ? "Сохранённые immutable-варианты" : "Saved immutable variants"}</strong>
          <span className="muted">{ru ? "Просмотр не меняет проект. Переключение головы сохраняет остальные два варианта." : "Inspecting does not change the project. Switching the head keeps the other two variants."}</span>
          <div className="row" style={{ flexWrap: "wrap", alignItems: "stretch" }}>
            {family.members.map((member) => {
              const isHead = member.version_id === headVersionId;
              const isActive = member.version_id === activeVersionId;
              return (
                <div className="card stack" key={member.version_id} style={{ flex: "1 1 160px" }}>
                  <div className="row"><strong>{member.label}</strong>{isHead ? <span className="status-green">{ru ? "Текущая" : "Current head"}</span> : null}</div>
                  <span className="mono">{[member.width_mm, member.depth_mm, member.height_mm].map((value) => value.toLocaleString(ru ? "ru-RU" : "en-US", { maximumFractionDigits: 3 })).join(" × ")} mm</span>
                  <button className={`btn ${isActive ? "primary" : ""}`} type="button" onClick={() => onInspect(member.version_id)}>{isActive ? (ru ? "Открыт" : "Inspecting") : (ru ? "Осмотреть" : "Inspect")}</button>
                  {canSelect ? (
                    <button className="btn" type="button" disabled={saving || isHead} onClick={() => void select(member.label)}>{isHead ? (ru ? "Выбран" : "Selected") : (ru ? "Сделать текущим" : "Switch project head")}</button>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : !loading ? <span className="muted">{ru ? "Сохранённого семейства пока нет." : "No saved family yet."}</span> : null}
    </div>
  );
}
