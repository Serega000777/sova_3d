import type { SplitProvenance } from "@physical-ai/contracts";
import { Text, View } from "react-native";

import { buildPlatePreviewModel } from "@/src/build-plate-preview";
import { colors, styles } from "@/src/theme";

const PALETTE = ["#F97316", "#38BDF8", "#84CC16", "#C084FC", "#FACC15", "#2DD4BF"];

function percent(value: number): `${number}%` {
  return `${Math.max(0, Math.min(100, value))}%`;
}

export function BuildPlatePreview({ layout }: { layout: SplitProvenance }) {
  const model = buildPlatePreviewModel(layout);
  if (!model) return null;
  return (
    <View style={{ gap: 6 }} accessibilityLabel={`Раскладка ${model.shapes.length} деталей на столе ${model.bedX.toFixed(0)} на ${model.bedY.toFixed(0)} миллиметров`}>
      <View style={{ width: "100%", aspectRatio: model.bedX / model.bedY, maxHeight: 420, position: "relative", overflow: "hidden", borderWidth: 1, borderColor: colors.border, borderRadius: 10, backgroundColor: colors.viewport }}>
        {model.shapes.map((shape, index) => (
          <View
            key={shape.id}
            style={{
              position: "absolute",
              left: percent(shape.leftPct),
              bottom: percent(shape.bottomPct),
              width: percent(shape.widthPct),
              height: percent(shape.heightPct),
              minWidth: 8,
              minHeight: 8,
              alignItems: "center",
              justifyContent: "center",
              borderWidth: 1,
              borderColor: colors.text,
              borderRadius: shape.kind === "dowel" ? 999 : 3,
              backgroundColor: PALETTE[index % PALETTE.length],
              opacity: 0.82,
            }}
          >
            <Text numberOfLines={1} style={[styles.muted, { color: colors.text, fontSize: 10 }]}>{shape.label}</Text>
          </View>
        ))}
      </View>
      <Text style={styles.muted}>Ограничивающие контуры показаны в масштабе реального стола; сервер уже проверил край и зазор между деталями.</Text>
    </View>
  );
}
