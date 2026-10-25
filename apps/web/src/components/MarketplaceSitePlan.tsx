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
      </div>
      <div className="row">
        {site.object_roles.map((role) => <span className="chip" key={role}>{OBJECT_LABELS[role][language]}</span>)}
      </div>
    </section>
  );
}
