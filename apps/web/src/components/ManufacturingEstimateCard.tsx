"use client";

import type {
  ManufacturingEstimate,
  PrintAnalysis,
  Schemas,
} from "@physical-ai/contracts";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  calculateManufacturingEstimate,
  manufacturingEstimateInput,
  manufacturingMetrics,
  type ManufacturingRateDraft,
} from "../lib/manufacturing-estimate";

interface ManufacturingEstimateCardProps {
  analysis: PrintAnalysis;
  savedEstimate: ManufacturingEstimate | null;
  loading: boolean;
  saving: boolean;
  canCreate: boolean;
  language: "ru" | "en";
  onCreate: (input: Schemas["ManufacturingEstimateBody"]) => Promise<void>;
}

const EMPTY_RATES: ManufacturingRateDraft = {
  machineRatePerHour: "",
  printerPowerW: "",
  electricityRatePerKwh: "",
  postprocessHours: "",
  postprocessRatePerHour: "",
};

export function ManufacturingEstimateCard({
  analysis,
  savedEstimate,
  loading,
  saving,
  canCreate,
  language,
  onCreate,
}: ManufacturingEstimateCardProps) {
  const ru = language === "ru";
  const metrics = manufacturingMetrics(analysis);
  const [rates, setRates] = useState<ManufacturingRateDraft>(EMPTY_RATES);
  const [dirty, setDirty] = useState(false);
  const hydratedEstimateId = useRef<string | null>(null);

  useEffect(() => {
    setRates(EMPTY_RATES);
    setDirty(false);
    hydratedEstimateId.current = null;
  }, [analysis.id]);

  useEffect(() => {
    if (!savedEstimate || dirty || hydratedEstimateId.current === savedEstimate.id) return;
    setRates({
      machineRatePerHour: savedEstimate.machine_rate_per_hour ?? "",
      printerPowerW: savedEstimate.printer_power_w ?? "",
      electricityRatePerKwh: savedEstimate.electricity_rate_per_kwh ?? "",
      postprocessHours: savedEstimate.postprocess_hours ?? "",
      postprocessRatePerHour: savedEstimate.postprocess_rate_per_hour ?? "",
    });
    hydratedEstimateId.current = savedEstimate.id;
  }, [dirty, savedEstimate]);

  const preview = useMemo(
    () => metrics
      ? calculateManufacturingEstimate(metrics.total_cost, metrics.print_time_min, rates)
      : null,
    [metrics, rates],
  );

  function updateRate(key: keyof ManufacturingRateDraft, value: string) {
    setRates((current) => ({ ...current, [key]: value }));
    setDirty(true);
  }

  async function createEstimate() {
    const input = manufacturingEstimateInput(rates);
    if (!input || !preview?.valid || saving || !canCreate) return;
    try {
      await onCreate(input);
      setDirty(false);
    } catch {
      // The page owns the shared error banner; keep the edited rates available for retry.
    }
  }

  if (!metrics) return null;
  const currency = metrics.currency;
  const money = (value: number | string | null | undefined) =>
    value == null ? "—" : Number(value).toFixed(2);
  const input = (
    label: string,
    key: keyof ManufacturingRateDraft,
    placeholder: string,
  ) => (
    <label className="stack" style={{ flex: "1 1 150px" }}>
      <span className="muted">{label}</span>
      <input
        className="input mono"
        type="number"
        min="0"
        step="0.01"
        inputMode="decimal"
        placeholder={placeholder}
        value={rates[key]}
        disabled={!canCreate || saving}
        onChange={(event) => updateRate(key, event.target.value)}
      />
    </label>
  );

  return (
    <div className="card stack" aria-label={ru ? "Смета производства" : "Manufacturing cost estimate"}>
      <strong>{ru ? "Смета производства" : "Manufacturing cost estimate"}</strong>
      <span>
        {ru ? "Материал" : "Material"}: {metrics.mass_g?.toFixed(1) ?? "—"} g
        {metrics.support_mass_g != null
          ? ` · ${ru ? "поддержки" : "supports"} ${metrics.support_mass_g.toFixed(1)} g`
          : ""}
      </span>
      <span>
        {ru ? "Печать" : "Print"}: {metrics.layers ?? "—"} {ru ? "слоёв" : "layers"}
        {` · ~${Math.round(metrics.print_time_min)} min`}
      </span>
      <span>
        {ru ? "Пластик" : "Filament"}: {money(metrics.material_cost)} {currency}
        {` · ${ru ? "поддержки" : "supports"} ${money(metrics.support_cost)} ${currency}`}
      </span>
      <strong>
        {ru ? "Итого материалов" : "Consumables total"}: {money(metrics.total_cost)} {currency}
      </strong>

      <span className="muted">
        {ru
          ? "Необязательно: введите собственные ставки. Приложение не подставляет тарифы и не выдаёт эту внутреннюю смету за предложение подрядчика."
          : "Optional: enter your own rates. The app supplies no default tariffs and does not present this internal estimate as a supplier quote."}
      </span>
      <div className="row" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
        {input(ru ? "Ставка машины в час" : "Machine rate per hour", "machineRatePerHour", ru ? "Машина / ч" : "Machine / h")}
        {input(ru ? "Мощность принтера, Вт" : "Printer power, W", "printerPowerW", ru ? "Мощность, Вт" : "Power, W")}
        {input(ru ? "Тариф электричества за кВт·ч" : "Electricity rate per kWh", "electricityRatePerKwh", ru ? "Электричество / кВт·ч" : "Electricity / kWh")}
      </div>
      <div className="row" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
        {input(ru ? "Часы постобработки" : "Post-processing hours", "postprocessHours", ru ? "Постобработка, ч" : "Post-process, h")}
        {input(ru ? "Ставка постобработки в час" : "Post-processing rate per hour", "postprocessRatePerHour", ru ? "Работа / ч" : "Labour / h")}
      </div>

      {preview?.valid ? (
        <div className="stack" aria-label={ru ? "Итоги сметы" : "Estimate totals"}>
          <span>
            {ru ? "Машина" : "Machine"}: {preview.machineCost.toFixed(2)} {currency}
            {` · ${ru ? "электричество" : "electricity"}: ${preview.electricityCost.toFixed(2)} ${currency}`}
          </span>
          <span>{ru ? "Постобработка" : "Post-processing"}: {preview.postprocessCost.toFixed(2)} {currency}</span>
          <strong>{ru ? "Расчётный итог" : "Estimated total"}: {preview.totalCost.toFixed(2)} {currency}</strong>
        </div>
      ) : preview ? (
        <span className="status-yellow">
          {preview.error === "incomplete_electricity"
            ? (ru ? "Для электричества нужны и мощность, и тариф." : "Electricity needs both power and a rate.")
            : preview.error === "incomplete_postprocess"
              ? (ru ? "Для постобработки нужны и часы, и ставка." : "Post-processing needs both hours and a rate.")
              : (ru ? "Расходы должны быть конечными неотрицательными числами." : "Costs must be finite non-negative numbers.")}
        </span>
      ) : null}

      {loading ? <span className="muted">{ru ? "Загружаем сохранённую смету…" : "Loading saved estimate…"}</span> : null}
      {savedEstimate && !dirty ? (
        <span className="status-green">
          {ru ? "Сохранённый снимок" : "Saved snapshot"}: {new Date(savedEstimate.created_at).toLocaleString(ru ? "ru-RU" : "en-US")}
          {` · ${money(savedEstimate.total_cost)} ${savedEstimate.currency}`}
        </span>
      ) : null}
      {canCreate ? (
        <button
          className="btn primary"
          type="button"
          disabled={!preview?.valid || saving}
          onClick={() => void createEstimate()}
        >
          {saving ? (ru ? "Сохраняем…" : "Saving…") : (ru ? "Сохранить смету" : "Save estimate")}
        </button>
      ) : (
        <span className="muted">{ru ? "Просмотр: создавать сметы может редактор." : "Read only: an editor can create estimates."}</span>
      )}
      <span className="muted">
        {ru
          ? "Материалы и время приходят из точного серверного анализа. Снимок привязан к этой версии, профилю и материалу и пересчитывается сервером. Обслуживание, доставка, налоги и наценка подрядчика не включены."
          : "Materials and time come from the exact server analysis. The snapshot is bound to this version, profile, and material and is recomputed by the server. Maintenance, shipping, taxes, and supplier markup are excluded."}
      </span>
    </div>
  );
}
