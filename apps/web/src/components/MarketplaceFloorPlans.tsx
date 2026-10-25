"use client";

import type { FloorPlan, Listing, PlanOpening } from "@physical-ai/contracts";
import { useMemo, useState } from "react";

import { PlanPreview } from "@/components/PlanEditor";

type Language = "en" | "ru";
type FloorPlanRow = Listing["floor_plans"][number];

export function MarketplaceFloorPlans({
  levels,
  language,
}: {
  levels: readonly FloorPlanRow[];
  language: Language;
}) {
  const [selectedFloor, setSelectedFloor] = useState(levels[0]?.floor_index ?? 0);
  const selected = useMemo(
    () => levels.find((level) => level.floor_index === selectedFloor) ?? levels[0] ?? null,
    [levels, selectedFloor],
  );
  if (!selected) return null;
  const ru = language === "ru";
  const previewPlan: FloorPlan = {
    ...selected.plan,
    openings: selected.plan.openings.map((opening) => ({
      ...opening,
      kind: opening.kind as PlanOpening["kind"],
      height_mm: opening.height_mm ?? undefined,
    })),
  };

  return (
    <section className="card stack" aria-label={ru ? "Поэтажные планы" : "Floor plans"}>
      <div>
        <strong>{ru ? "Поэтажные планы" : "Floor plans"}</strong>
        <div className="muted">
          {ru
            ? "Структурированный план из опубликованной неизменяемой версии; PDF-паспорт доступен на карточке товара."
            : "A structured plan from the published immutable version; its PDF house document is available on the listing."}
        </div>
      </div>
      <div className="row" role="tablist" aria-label={ru ? "Этажи" : "Floors"}>
        {levels.map((level) => (
          <button
            type="button"
            role="tab"
            aria-selected={level.floor_index === selected.floor_index}
            className={`chip ${level.floor_index === selected.floor_index ? "selected" : ""}`}
            key={level.floor_index}
            onClick={() => setSelectedFloor(level.floor_index)}
          >
            {ru ? `${level.floor_index + 1} этаж` : `Floor ${level.floor_index + 1}`}
          </button>
        ))}
      </div>
      <PlanPreview plan={previewPlan} />
      <div className="row">
        <span className="chip">{selected.plan.walls.length} {ru ? "стен" : "walls"}</span>
        {selected.plan.rooms.length > 0 && (
          <span className="chip">{selected.plan.rooms.length} {ru ? "комн." : "rooms"}</span>
        )}
        <span className="chip mono">
          {ru ? "Отметка" : "Elevation"}: {(selected.elevation_mm / 1000).toFixed(1)} m
        </span>
      </div>
    </section>
  );
}
