export type MaterialExecutionStats = {
  material_assigned_regions?: number;
  planned_tool_change_layers?: number;
  planned_tool_changes?: number;
  planned_purge_volume_mm3?: number;
  purge_tower_reserved?: boolean;
  purge_tower_width_mm?: number;
};

function formatMetric(value: number): string {
  return String(value);
}

/** Describe only execution facts frozen into the completed slice result. */
export function describeMaterialExecution(stats: MaterialExecutionStats): string | null {
  const changes = stats.planned_tool_changes;
  const layers = stats.planned_tool_change_layers;
  if (changes == null || layers == null) return null;
  if (changes === 0) return "физических переходов в этом slice нет";

  const details = [`физические переходы: ${changes} на ${layers} слоях`];
  if (stats.planned_purge_volume_mm3 != null) {
    details.push(`purge ${formatMetric(stats.planned_purge_volume_mm3)} мм³`);
  }
  if (stats.purge_tower_reserved != null) {
    const tower = stats.purge_tower_reserved
      ? "purge-башня зарезервирована"
      : "purge-башня не зарезервирована";
    details.push(
      stats.purge_tower_width_mm == null
        ? tower
        : `${tower}, ширина ${formatMetric(stats.purge_tower_width_mm)} мм`,
    );
  } else if (stats.purge_tower_width_mm != null) {
    details.push(`ширина purge-башни ${formatMetric(stats.purge_tower_width_mm)} мм`);
  }
  return details.join(" · ");
}

export type MaterialSummary = {
  assignment: string | null;
  execution: string | null;
};

/** Keep assignment metadata and physical execution facts independently conditional. */
export function composeMaterialSummary(stats: MaterialExecutionStats): MaterialSummary {
  const assigned = stats.material_assigned_regions ?? 0;
  return {
    assignment: assigned > 0 ? `материал назначен ${assigned} областям` : null,
    execution: describeMaterialExecution(stats),
  };
}
