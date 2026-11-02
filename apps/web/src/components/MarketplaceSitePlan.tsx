import type { Listing } from "@physical-ai/contracts";

type Language = "en" | "ru";
type SitePlan = NonNullable<Listing["site_plan"]>;

const OBJECT_LABELS = {
  house: { ru: "Дом", en: "House" },
  terrain: { ru: "Рельеф", en: "Terrain" },
  pad: { ru: "Площадка дома", en: "House pad" },
  path: { ru: "Дорожка", en: "Path" },
  fence: { ru: "Ограждение", en: "Fence" },
} as const;

export function MarketplaceSitePlan({ site, language }: { site: SitePlan; language: Language }) {
  const ru = language === "ru";
  const width = 600;
  const height = 400;
  const padding = 24;
  const scaleX = (width - 2 * padding) / site.plot_length_mm;
  const scaleY = (height - 2 * padding) / site.plot_width_mm;
  const point = ([x, y]: readonly number[]) => [
    width / 2 + x * scaleX,
    height / 2 - y * scaleY,
  ] as const;
  const house = point([site.house_x_mm, site.house_y_mm]);
  const houseWidth = site.house_dimensions_mm[0] * scaleX;
  const houseHeight = site.house_dimensions_mm[1] * scaleY;
  const path = site.path_points_mm.map((value) => point(value).join(",")).join(" ");
  const fence = new Set(site.fence_sides);
  const [requiredNorth, requiredEast, requiredSouth, requiredWest] = site.required_boundary_clearances_mm;
  const clearanceX = padding + requiredWest * scaleX;
  const clearanceY = padding + requiredNorth * scaleY;
  const clearanceWidth = Math.max(0, width - 2 * padding - (requiredWest + requiredEast) * scaleX);
  const clearanceHeight = Math.max(0, height - 2 * padding - (requiredNorth + requiredSouth) * scaleY);
  const minimumMeasuredClearance = Math.min(...site.house_boundary_clearances_mm);

  return (
    <section className="card stack" aria-label={ru ? "План участка" : "Site plan"}>
      <div>
        <strong>{ru ? "Композиция участка" : "Site composition"}</strong>
        <div className="muted">
          {ru
            ? "Размеры и объекты подтверждены успешной неизменяемой сборкой участка."
            : "Dimensions and objects are backed by the successful immutable site composition."}
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ru ? "План участка с домом, дорожкой и ограждением" : "Plot with house, path and fence"}>
        <rect x={padding} y={padding} width={width - 2 * padding} height={height - 2 * padding} rx="4" fill="var(--panel-2)" stroke="var(--border)" />
        <rect x={clearanceX} y={clearanceY} width={clearanceWidth} height={clearanceHeight} fill="none" stroke="var(--muted)" strokeDasharray="7 5" />
        {fence.has("north") && <line x1={padding} y1={padding} x2={width - padding} y2={padding} stroke="var(--accent)" strokeWidth="5" />}
        {fence.has("south") && <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="var(--accent)" strokeWidth="5" />}
        {fence.has("west") && <line x1={padding} y1={padding} x2={padding} y2={height - padding} stroke="var(--accent)" strokeWidth="5" />}
        {fence.has("east") && <line x1={width - padding} y1={padding} x2={width - padding} y2={height - padding} stroke="var(--accent)" strokeWidth="5" />}
        <polyline points={path} fill="none" stroke="var(--muted)" strokeWidth={Math.max(3, site.path_width_mm * Math.min(scaleX, scaleY))} strokeLinecap="round" strokeLinejoin="round" />
        <g transform={`translate(${house[0]} ${house[1]}) rotate(${-site.house_rotation_deg})`}>
          <rect x={-houseWidth / 2} y={-houseHeight / 2} width={houseWidth} height={houseHeight} fill="var(--accent-wash-strong)" stroke="var(--accent)" strokeWidth="2" />
          <text x="0" y="4" textAnchor="middle" fill="currentColor" fontSize="14">{ru ? "Дом" : "House"}</text>
        </g>
      </svg>
      <div className="row">
        <span className="chip mono">{(site.plot_length_mm / 1000).toFixed(1)} × {(site.plot_width_mm / 1000).toFixed(1)} m</span>
        <span className="chip mono">{ru ? "Поворот дома" : "House rotation"}: {site.house_rotation_deg.toFixed(0)}°</span>
        <span className="chip mono">{ru ? "Перепад" : "Elevation range"}: {(Math.max(...site.corner_elevations_mm) - Math.min(...site.corner_elevations_mm)).toFixed(0)} mm</span>
        <span className="chip mono">{ru ? "Мин. отступ" : "Min clearance"}: {minimumMeasuredClearance.toFixed(0)} mm ≥ {site.minimum_boundary_clearance_mm.toFixed(0)} mm</span>
      </div>
      {site.boundary_rule_set && <div className="stack">
        <strong>{site.boundary_rule_set.jurisdiction} · {site.boundary_rule_set.title}</strong>
        <span className="muted">{ru ? "Версия" : "Version"} {site.boundary_rule_set.source_version} · {site.boundary_rule_set.effective_date} · {site.boundary_rule_set.source_url}</span>
        <span className="chip mono">N {requiredNorth.toFixed(0)} · E {requiredEast.toFixed(0)} · S {requiredSouth.toFixed(0)} · W {requiredWest.toFixed(0)} mm</span>
      </div>}
      <div className="muted">{ru
        ? "Пунктир — эффективные требования: максимум общего отступа и сохранённого owner-declared источника по каждой стороне. Сервер измерил геометрию, но не подтверждает юридическую применимость или актуальность источника."
        : "The dashed envelope uses the greater of the general clearance and the stored owner-declared source for each side. The server measures geometry but does not certify that the source is legally applicable or current."}</div>
      <div className="row">
        {site.object_roles.map((role) => <span className="chip" key={role}>{OBJECT_LABELS[role][language]}</span>)}
      </div>
    </section>
  );
}
