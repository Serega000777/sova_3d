import { type ReactNode, useMemo, useRef, useState } from "react";
import { PanResponder, Pressable, ScrollView, Text, View } from "react-native";

import type { DrawMode } from "./ModelViewer";
import { colors, styles } from "./theme";

export type WorkspaceTab = "properties" | "check" | "versions" | "export";

interface WorkspaceShellProps {
  isTablet: boolean;
  projectName: string;
  versionLabel: string | null;
  viewMode: "2d" | "3d";
  onViewModeChange: (mode: "2d" | "3d") => void;
  mode: DrawMode;
  modelAvailable: boolean;
  activeAvailable: boolean;
  onTool: (tool: "select" | "paint" | "mesh" | "grid" | "layers" | "dimensions") => void;
  viewer: ReactNode;
  planViewer?: ReactNode;
  hasFloorPlan?: boolean;
  linkedSelection?: boolean;
  onLinkedSelectionChange?: (linked: boolean) => void;
  linkNotice?: string | null;
  planFallbackNotice?: string | null;
  composer: ReactNode;
  tab: WorkspaceTab;
  onTabChange: (tab: WorkspaceTab) => void;
  inspector: ReactNode;
  regionLabel?: string | null;
  onClearRegion?: () => void;
}

const TOOLS: Array<{
  id: "select" | "paint" | "mesh" | "grid" | "layers" | "dimensions";
  glyph: string;
  label: string;
  needsModel?: boolean;
}> = [
  { id: "select", glyph: "⌁", label: "Выделить", needsModel: true },
  { id: "paint", glyph: "◒", label: "Цвет", needsModel: true },
  { id: "mesh", glyph: "◇", label: "Форма", needsModel: true },
  { id: "grid", glyph: "▦", label: "Сетка", needsModel: true },
  { id: "layers", glyph: "▱", label: "Слои" },
  { id: "dimensions", glyph: "↔", label: "Размеры", needsModel: true },
];

const TABS: Array<{ id: WorkspaceTab; label: string }> = [
  { id: "properties", label: "Объект" },
  { id: "check", label: "Проверка" },
  { id: "versions", label: "Версии" },
  { id: "export", label: "Экспорт" },
];

export function WorkspaceShell({
  isTablet,
  projectName,
  versionLabel,
  viewMode,
  onViewModeChange,
  mode,
  modelAvailable,
  activeAvailable,
  onTool,
  viewer,
  planViewer,
  hasFloorPlan = false,
  linkedSelection = true,
  onLinkedSelectionChange,
  linkNotice,
  planFallbackNotice,
  composer,
  tab,
  onTabChange,
  inspector,
  regionLabel,
  onClearRegion,
}: WorkspaceShellProps) {
  const [paneRatio, setPaneRatio] = useState(0.46);
  const [swapped, setSwapped] = useState(false);
  const [expanded, setExpanded] = useState<"plan" | "model" | null>(null);
  const splitWidth = useRef(1);
  const dragStartRatio = useRef(paneRatio);
  const paneRatioRef = useRef(paneRatio);
  paneRatioRef.current = paneRatio;
  const dividerPan = useMemo(
    () =>
      PanResponder.create({
        onMoveShouldSetPanResponder: (_, gesture) => Math.abs(gesture.dx) > 3,
        onPanResponderGrant: () => {
          dragStartRatio.current = paneRatioRef.current;
        },
        onPanResponderMove: (_, gesture) => {
          const direction = swapped ? -1 : 1;
          const next = dragStartRatio.current + (gesture.dx * direction) / Math.max(splitWidth.current, 1);
          setPaneRatio(Math.max(0.25, Math.min(0.75, next)));
        },
      }),
    [swapped],
  );
  const activeTool =
    mode === "outline" ? "select" : mode === "paint" ? "paint" : mode === "edit" ? "mesh" : null;

  const toolbar = (
    <ScrollView
      horizontal={!isTablet}
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={isTablet ? { gap: 8 } : { gap: 8, paddingHorizontal: 2 }}
      style={isTablet ? undefined : { flexGrow: 0 }}
    >
      {TOOLS.map((tool) => {
        const disabled = tool.id === "layers" ? !activeAvailable : Boolean(tool.needsModel && !modelAvailable);
        const isActive = activeTool === tool.id;
        return (
          <Pressable
            key={tool.id}
            accessibilityRole="button"
            accessibilityLabel={tool.label}
            disabled={disabled}
            onPress={() => onTool(tool.id)}
            style={[
              {
                width: isTablet ? 76 : 72,
                minHeight: isTablet ? 60 : 54,
                paddingHorizontal: 8,
                paddingVertical: 8,
                alignItems: "center",
                justifyContent: "center",
                gap: 4,
                borderRadius: 12,
                borderWidth: 1,
                borderColor: isActive ? colors.accent : colors.border,
                backgroundColor: isActive ? colors.accentWashStrong : colors.panel2,
              },
              disabled && { opacity: 0.38 },
            ]}
          >
            <Text style={{ color: isActive ? colors.accent : colors.text, fontSize: 19 }}>{tool.glyph}</Text>
            <Text style={{ color: isActive ? colors.accent : colors.muted, fontSize: 11, fontWeight: "600" }}>
              {tool.label}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );

  const tabBar = (
    <View style={{ flexDirection: "row", borderBottomColor: colors.border, borderBottomWidth: 1 }}>
      {TABS.map((item) => (
        <Pressable
          key={item.id}
          onPress={() => onTabChange(item.id)}
          style={{ flex: 1, alignItems: "center", paddingVertical: 12, borderBottomWidth: 2, borderBottomColor: tab === item.id ? colors.accent : "transparent" }}
        >
          <Text style={{ color: tab === item.id ? colors.accent : colors.muted, fontSize: 11, fontWeight: "700" }}>
            {item.label}
          </Text>
        </Pressable>
      ))}
    </View>
  );

  return (
    <View style={{ borderColor: colors.border, borderWidth: 1, borderRadius: 18, overflow: "hidden", backgroundColor: colors.viewport }}>
      <View style={{ minHeight: 54, paddingHorizontal: 14, paddingVertical: 10, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10, backgroundColor: colors.panel, borderBottomColor: colors.border, borderBottomWidth: 1 }}>
        <View style={{ flex: 1 }}>
          <Text style={styles.heading} numberOfLines={1}>{projectName}</Text>
          <Text style={styles.muted}>{versionLabel ? `${versionLabel} · сохранено` : "Новая модель"}</Text>
        </View>
        {isTablet && hasFloorPlan ? (
          <View style={[styles.chip, { borderColor: colors.accent }]}>
            <Text style={[styles.chipText, { color: colors.accent }]}>План ↔ Модель</Text>
          </View>
        ) : (
          <View style={{ flexDirection: "row", padding: 3, borderRadius: 10, backgroundColor: colors.bg, borderColor: colors.border, borderWidth: 1 }}>
            {(["2d", "3d"] as const).map((value) => (
              <Pressable
                key={value}
                onPress={() => onViewModeChange(value)}
                style={{ paddingHorizontal: 13, paddingVertical: 7, borderRadius: 8, backgroundColor: viewMode === value ? colors.accent : "transparent" }}
              >
                <Text style={{ color: viewMode === value ? "#160b05" : colors.text, fontSize: 12, fontWeight: "800" }}>{value.toUpperCase()}</Text>
              </Pressable>
            ))}
          </View>
        )}
      </View>

      {isTablet ? (
        <View style={{ flexDirection: "row", minHeight: 590 }}>
          <View style={{ width: 96, padding: 10, backgroundColor: colors.panel, borderRightColor: colors.border, borderRightWidth: 1 }}>
            {toolbar}
          </View>
          <View style={{ flex: 1, minWidth: 0, padding: 10, gap: 10 }}>
            {hasFloorPlan && planViewer ? (
              <View
                style={{ flexDirection: swapped ? "row-reverse" : "row", minWidth: 0 }}
                onLayout={(event) => {
                  splitWidth.current = Math.max(event.nativeEvent.layout.width - 52, 1);
                }}
              >
                <View
                  style={{
                    display: expanded === "model" ? "none" : "flex",
                    flexBasis: expanded ? undefined : `${paneRatio * 100}%`,
                    flexGrow: expanded === "plan" ? 1 : 0,
                    minWidth: 0,
                  }}
                >
                  {planViewer}
                </View>
                <View
                  {...dividerPan.panHandlers}
                  accessibilityLabel="Разделитель связанных представлений"
                  style={{
                    width: 52,
                    minHeight: 520,
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 8,
                    backgroundColor: colors.panel,
                    borderColor: colors.border,
                    borderLeftWidth: 1,
                    borderRightWidth: 1,
                  }}
                >
                  <Pressable
                    accessibilityRole="switch"
                    accessibilityState={{ checked: linkedSelection }}
                    accessibilityLabel="Связать выделение"
                    onPress={() => onLinkedSelectionChange?.(!linkedSelection)}
                    style={[styles.chip, { paddingHorizontal: 8 }, linkedSelection && { borderColor: colors.accent }]}
                  >
                    <Text style={{ color: linkedSelection ? colors.accent : colors.muted, fontWeight: "800" }}>⌁</Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="Поменять панели местами"
                    onPress={() => setSwapped((value) => !value)}
                    style={[styles.chip, { paddingHorizontal: 8 }]}
                  >
                    <Text style={styles.chipText}>⇄</Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="Развернуть левую панель"
                    onPress={() => {
                      const pane = swapped ? "model" : "plan";
                      setExpanded((value) => value === pane ? null : pane);
                    }}
                    style={[styles.chip, { paddingHorizontal: 8 }]}
                  >
                    <Text style={styles.chipText}>←</Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="Развернуть правую панель"
                    onPress={() => {
                      const pane = swapped ? "plan" : "model";
                      setExpanded((value) => value === pane ? null : pane);
                    }}
                    style={[styles.chip, { paddingHorizontal: 8 }]}
                  >
                    <Text style={styles.chipText}>→</Text>
                  </Pressable>
                  <Text style={{ color: colors.muted, fontSize: 14 }}>⋮</Text>
                </View>
                <View
                  style={{
                    display: expanded === "plan" ? "none" : "flex",
                    flex: 1,
                    minWidth: 0,
                  }}
                >
                  {viewer}
                </View>
              </View>
            ) : viewer}
            {linkNotice && <Text style={[styles.muted, { color: colors.yellow }]}>{linkNotice}</Text>}
            {!hasFloorPlan && planFallbackNotice && <Text style={styles.muted}>{planFallbackNotice}</Text>}
            {regionLabel && (
              <Pressable style={[styles.chip, { alignSelf: "flex-start", borderColor: colors.accent }]} onPress={onClearRegion}>
                <Text style={[styles.chipText, { color: colors.accent }]}>{regionLabel} · убрать</Text>
              </Pressable>
            )}
            {composer}
          </View>
          <View style={{ width: 318, backgroundColor: colors.panel, borderLeftColor: colors.border, borderLeftWidth: 1 }}>
            {tabBar}
            <ScrollView contentContainerStyle={{ padding: 14, gap: 12 }}>{inspector}</ScrollView>
          </View>
        </View>
      ) : (
        <View style={{ gap: 10, padding: 10 }}>
          {hasFloorPlan && planViewer ? (
            <View>
              <View style={{ display: viewMode === "2d" ? "flex" : "none" }}>{planViewer}</View>
              <View style={{ display: viewMode === "3d" ? "flex" : "none" }}>{viewer}</View>
            </View>
          ) : viewer}
          {linkNotice && <Text style={[styles.muted, { color: colors.yellow }]}>{linkNotice}</Text>}
          {!hasFloorPlan && planFallbackNotice && <Text style={styles.muted}>{planFallbackNotice}</Text>}
          {toolbar}
          {regionLabel && (
            <Pressable style={[styles.chip, { alignSelf: "flex-start", borderColor: colors.accent }]} onPress={onClearRegion}>
              <Text style={[styles.chipText, { color: colors.accent }]}>{regionLabel} · убрать</Text>
            </Pressable>
          )}
          {composer}
          <View style={{ marginHorizontal: -10, marginBottom: -10, borderTopColor: colors.border, borderTopWidth: 1, backgroundColor: colors.panel }}>
            {tabBar}
            <View style={{ padding: 14, gap: 12 }}>{inspector}</View>
          </View>
        </View>
      )}
    </View>
  );
}
