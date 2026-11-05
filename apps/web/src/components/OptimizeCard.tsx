"use client";

import type {
  Material,
  PrinterProfile,
  ThumbnailUrlSet,
  Version,
  VersionComparison,
} from "@physical-ai/contracts";

import { VersionImageComparison } from "./VersionImageComparison";

export interface OptimizationDraft {
  version: Version;
  diff: VersionComparison;
  beforeUrls: ThumbnailUrlSet;
  afterUrls: ThumbnailUrlSet;
  beforeMassG?: number;
  afterMassG?: number;
  materialName?: string;
  description?: string;
}

interface OptimizeCardProps {
  printers: PrinterProfile[];
  materials: Material[];
  printerProfileId: string;
  materialId: string;
  operationStackStatus: "loading" | "present" | "absent" | "error";
  draft: OptimizationDraft | null;
  disabled: boolean;
  deciding: boolean;
  language: "ru" | "en";
  onPrinterProfileChange: (id: string) => void;
  onMaterialChange: (id: string) => void;
  onOptimize: () => Promise<void>;
  onDecide: (keep: boolean) => Promise<void>;
}

function dimensions(value: number[] | null | undefined): string {
  return value?.length === 3 ? `${value.map((item) => item.toFixed(1)).join(" × ")} mm` : "—";
}

function volume(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value).toLocaleString("en-US")} mm³`;
}

export function OptimizeCard({
  printers,
  materials,
  printerProfileId,
  materialId,
  operationStackStatus,
  draft,
  disabled,
  deciding,
  language,
  onPrinterProfileChange,
  onMaterialChange,
  onOptimize,
  onDecide,
}: OptimizeCardProps) {
  const ru = language === "ru";
  const supported = operationStackStatus === "present";
  const selectedMaterial = materials.find((item) => item.id === materialId);
  const massMaterialName = draft?.materialName ?? selectedMaterial?.name;

  return (
    <div className="card stack" aria-label={ru ? "Оптимизация геометрии" : "Geometry optimization"}>
      <strong>{ru ? "Облегчить параметрическую деталь" : "Lighten a parametric part"}</strong>
      <span className="muted">
        {ru
          ? "Сервер создаёт bottom-open оболочку с ограниченной структурной стенкой и сохраняет сплошные бобышки вокруг поддерживаемых отверстий. Это детерминированное правило, не FEA и не свободная оптимизация топологии."
          : "The server builds a bottom-open shell with a bounded structural wall and keeps solid bosses around supported holes. This is a deterministic rule, not FEA or free-form topology optimization."}
      </span>

      <div className="row" style={{ flexWrap: "wrap" }}>
        <label className="stack" style={{ flex: "1 1 220px" }}>
          <span className="muted">{ru ? "Профиль принтера" : "Printer profile"}</span>
          <select
            className="input"
            value={printerProfileId}
            disabled={disabled || deciding}
            onChange={(event) => onPrinterProfileChange(event.target.value)}
          >
            {printers.length === 0 ? (
              <option value="">{ru ? "Профиль не настроен" : "No configured profile"}</option>
            ) : null}
            {printers.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.name}{profile.is_default ? (ru ? " · по умолчанию" : " · default") : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="stack" style={{ flex: "1 1 220px" }}>
          <span className="muted">{ru ? "Материал" : "Material"}</span>
          <select
            className="input"
            value={materialId}
            disabled={disabled || deciding}
            onChange={(event) => onMaterialChange(event.target.value)}
          >
            {materials.length === 0 ? (
              <option value="">{ru ? "Системный материал" : "System default material"}</option>
            ) : null}
            {materials.map((material) => (
              <option key={material.id} value={material.id}>{material.name}</option>
            ))}
          </select>
        </label>
      </div>

      {operationStackStatus === "absent" ? (
        <span className="status-yellow" role="alert">
          {ru
            ? "Импортированный mesh без истории операций нельзя облегчить этим точным инструментом. Сначала восстановите параметрическую CAD-модель."
            : "An imported mesh without operation history cannot use this exact hollowing tool. Reconstruct a parametric CAD model first."}
        </span>
      ) : operationStackStatus !== "present" ? (
        <span className="muted">
          {operationStackStatus === "loading"
            ? (ru ? "Проверяем историю CAD-операций…" : "Checking CAD operation history…")
            : (ru ? "Историю CAD-операций проверить не удалось; оптимизация отключена." : "CAD operation history could not be verified; optimization is disabled.")}
        </span>
      ) : null}

      <button
        className="btn primary"
        type="button"
        disabled={disabled || deciding || !supported}
        onClick={() => void onOptimize()}
      >
        {ru ? "Подготовить облегчённый draft" : "Prepare lighter draft"}
      </button>

      {draft ? (
        <div className="stack" style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}>
          <strong>{ru ? "Draft ещё не применён" : "Draft not applied yet"}</strong>
          {draft.description ? <span className="muted">{draft.description}</span> : null}
          <VersionImageComparison
            beforeUrl={draft.beforeUrls.iso ?? null}
            currentUrl={draft.afterUrls.iso ?? null}
            beforeLabel={ru ? "До оптимизации" : "Before optimization"}
            currentLabel={ru ? "После оптимизации" : "After optimization"}
            language={language}
          />
          <div className="row" style={{ flexWrap: "wrap" }}>
            <span className="chip mono">
              {ru ? "До" : "Before"}: {dimensions(draft.diff.before?.size_mm)} · {volume(draft.diff.before?.volume_mm3)}
            </span>
            <span className="chip mono">
              {ru ? "После" : "After"}: {dimensions(draft.diff.after.size_mm)} · {volume(draft.diff.after.volume_mm3)}
            </span>
            {typeof draft.diff.changed.volume_delta_pct === "number" ? (
              <span className="chip mono">
                {ru ? "Δ объёма" : "Volume Δ"}: {draft.diff.changed.volume_delta_pct > 0 ? "+" : ""}{draft.diff.changed.volume_delta_pct}%
              </span>
            ) : null}
            {draft.beforeMassG !== undefined && draft.afterMassG !== undefined ? (
              <span className="chip mono">
                {ru ? "Масса" : "Mass"}: {draft.beforeMassG.toLocaleString(ru ? "ru-RU" : "en-US")} → {draft.afterMassG.toLocaleString(ru ? "ru-RU" : "en-US")} g
                {massMaterialName ? ` · ${massMaterialName}` : ""}
              </span>
            ) : null}
          </div>
          <div className="row">
            <button className="btn primary" type="button" disabled={disabled || deciding} onClick={() => void onDecide(true)}>
              {ru ? "Оставить" : "Keep"}
            </button>
            <button className="btn" type="button" disabled={disabled || deciding} onClick={() => void onDecide(false)}>
              {ru ? "Удалить draft" : "Discard"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
