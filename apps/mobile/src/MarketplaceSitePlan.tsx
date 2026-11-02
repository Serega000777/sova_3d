import type { Listing } from "@physical-ai/contracts";
import Svg, { G, Line, Polyline, Rect, Text as SvgText } from "react-native-svg";
import { Text, View } from "react-native";

import { colors, radii, styles } from "./theme";

type SitePlan = NonNullable<Listing["site_plan"]>;

const ROLE_LABELS: Record<SitePlan["object_roles"][number], string> = {
  house: "Дом",
  terrain: "Рельеф",
  pad: "Площадка",
  path: "Дорожка",
  fence: "Ограждение",
};

export function MarketplaceSitePlan({ site }: { site: SitePlan }) {
  const width = 600;
  const height = 400;
  const padding = 24;
  const scaleX = (width - 2 * padding) / site.plot_length_mm;
  const scaleY = (height - 2 * padding) / site.plot_width_mm;
  const point = ([x, y]: readonly number[]) => [width / 2 + x * scaleX, height / 2 - y * scaleY] as const;
  const house = point([site.house_x_mm, site.house_y_mm]);
  const houseWidth = site.house_dimensions_mm[0] * scaleX;
  const houseHeight = site.house_dimensions_mm[1] * scaleY;
  const path = site.path_points_mm.map((value) => point(value).join(",")).join(" ");
  const fence = new Set(site.fence_sides);
  const elevationRange = Math.max(...site.corner_elevations_mm) - Math.min(...site.corner_elevations_mm);
  const [requiredNorth, requiredEast, requiredSouth, requiredWest] = site.required_boundary_clearances_mm;
  const clearanceX = padding + requiredWest * scaleX;
  const clearanceY = padding + requiredNorth * scaleY;
  const clearanceWidth = Math.max(0, width - 2 * padding - (requiredWest + requiredEast) * scaleX);
  const clearanceHeight = Math.max(0, height - 2 * padding - (requiredNorth + requiredSouth) * scaleY);
  const minimumMeasuredClearance = Math.min(...site.house_boundary_clearances_mm);

  return (
    <View style={[styles.card, { gap: 10 }]} accessibilityLabel="План участка">
      <View style={{ gap: 3 }}>
        <Text style={styles.heading}>Композиция участка</Text>
        <Text style={styles.sectionSubtitle}>Размеры и объекты подтверждены успешной неизменяемой сборкой участка.</Text>
      </View>
      <View style={{ width: "100%", aspectRatio: 3 / 2, borderRadius: radii.control, overflow: "hidden", backgroundColor: colors.viewport }}>
        <Svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`} accessibilityLabel="Участок с домом, дорожкой и ограждением">
          <Rect x={padding} y={padding} width={width - 2 * padding} height={height - 2 * padding} rx={4} fill={colors.panel} stroke={colors.border} />
          <Rect x={clearanceX} y={clearanceY} width={clearanceWidth} height={clearanceHeight} fill="none" stroke={colors.muted} strokeDasharray="7 5" />
          {fence.has("north") ? <Line x1={padding} y1={padding} x2={width - padding} y2={padding} stroke={colors.accent} strokeWidth={5} /> : null}
          {fence.has("south") ? <Line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke={colors.accent} strokeWidth={5} /> : null}
          {fence.has("west") ? <Line x1={padding} y1={padding} x2={padding} y2={height - padding} stroke={colors.accent} strokeWidth={5} /> : null}
          {fence.has("east") ? <Line x1={width - padding} y1={padding} x2={width - padding} y2={height - padding} stroke={colors.accent} strokeWidth={5} /> : null}
          <Polyline points={path} fill="none" stroke={colors.muted} strokeWidth={Math.max(3, site.path_width_mm * Math.min(scaleX, scaleY))} strokeLinecap="round" strokeLinejoin="round" />
          <G transform={`translate(${house[0]} ${house[1]}) rotate(${-site.house_rotation_deg})`}>
            <Rect x={-houseWidth / 2} y={-houseHeight / 2} width={houseWidth} height={houseHeight} fill={colors.accentWashStrong} stroke={colors.accent} strokeWidth={2} />
            <SvgText x={0} y={4} textAnchor="middle" fill={colors.text} fontSize={14}>Дом</SvgText>
          </G>
        </Svg>
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        <View style={styles.chip}><Text style={styles.chipText}>{(site.plot_length_mm / 1000).toFixed(1)} × {(site.plot_width_mm / 1000).toFixed(1)} м</Text></View>
        <View style={styles.chip}><Text style={styles.chipText}>Дом: {site.house_rotation_deg.toFixed(0)}°</Text></View>
        <View style={styles.chip}><Text style={styles.chipText}>Перепад: {elevationRange.toFixed(0)} мм</Text></View>
        <View style={styles.chip}><Text style={styles.chipText}>Мин. отступ: {minimumMeasuredClearance.toFixed(0)} ≥ {site.minimum_boundary_clearance_mm.toFixed(0)} мм</Text></View>
      </View>
      {site.boundary_rule_set ? <View style={{ gap: 4 }}>
        <Text style={styles.heading}>{site.boundary_rule_set.jurisdiction} · {site.boundary_rule_set.title}</Text>
        <Text style={styles.sectionSubtitle}>Версия {site.boundary_rule_set.source_version} · {site.boundary_rule_set.effective_date}</Text>
        <Text style={styles.sectionSubtitle}>{site.boundary_rule_set.source_url}</Text>
        <Text style={styles.chipText}>N {requiredNorth.toFixed(0)} · E {requiredEast.toFixed(0)} · S {requiredSouth.toFixed(0)} · W {requiredWest.toFixed(0)} мм</Text>
      </View> : null}
      <Text style={styles.sectionSubtitle}>Пунктир — максимум общего отступа и сохранённого owner-declared источника по каждой стороне. Сервер проверяет геометрию, но не подтверждает юридическую применимость или актуальность источника.</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        {site.object_roles.map((role) => <View key={role} style={styles.statusBadge}><Text style={styles.statusText}>{ROLE_LABELS[role]}</Text></View>)}
      </View>
    </View>
  );
}
