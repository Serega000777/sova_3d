import type { FloorPlan, InteriorMaterial } from "@physical-ai/contracts";
import { useEffect, useMemo, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { colors, styles } from "@/src/theme";

export interface RoomWallEdit {
  wallIndex: number;
  offsetMm: number;
  thicknessMm: number;
  heightMm: number;
  materialId: string | null;
}

export function RoomWallEditor({
  plan,
  wallIndex,
  materials,
  busy,
  language,
  onSubmit,
}: {
  plan: FloorPlan;
  wallIndex: number;
  materials: InteriorMaterial[];
  busy: boolean;
  language: "ru" | "en";
  onSubmit: (edit: RoomWallEdit) => void;
}) {
  const wall = plan.walls[wallIndex];
  const ru = language === "ru";
  const wallMaterials = useMemo(
    () => materials.filter((material) => material.tabs.includes("wall")),
    [materials],
  );
  const [offset, setOffset] = useState("0");
  const [thickness, setThickness] = useState(String(wall?.thickness_mm ?? 120));
  const [height, setHeight] = useState(String(wall?.height_mm ?? 2_700));
  const [materialId, setMaterialId] = useState<string | null>(wall?.material_id ?? null);

  useEffect(() => {
    setOffset("0");
    setThickness(String(wall?.thickness_mm ?? 120));
    setHeight(String(wall?.height_mm ?? 2_700));
    setMaterialId(wall?.material_id ?? null);
  }, [wallIndex, wall?.height_mm, wall?.material_id, wall?.thickness_mm]);

  if (!wall) return null;
  const offsetMm = Number(offset.replace(",", "."));
  const thicknessMm = Number(thickness.replace(",", "."));
  const heightMm = Number(height.replace(",", "."));
  const valid =
    Number.isFinite(offsetMm) && offsetMm >= -5_000 && offsetMm <= 5_000
    && Number.isFinite(thicknessMm) && thicknessMm >= 20 && thicknessMm <= 2_000
    && Number.isFinite(heightMm) && heightMm >= 500 && heightMm <= 12_000;

  return (
    <View style={[styles.card, { gap: 10 }]} accessibilityLabel={ru ? "Редактор стены комнаты" : "Room wall editor"}>
      <Text style={styles.heading}>{ru ? `Стена ${wallIndex + 1}` : `Wall ${wallIndex + 1}`}</Text>
      <Text style={styles.muted}>
        {ru
          ? "Смещение переносит стену параллельно и сохраняет замкнутый контур. Сервер заново строит точную оболочку, а исходный скан остаётся в истории."
          : "Offset moves the wall in parallel and keeps the perimeter closed. The server rebuilds the exact shell while retaining the source scan."}
      </Text>
      <Text style={styles.muted}>{ru ? "Смещение, мм (знак задаёт сторону)" : "Offset, mm (sign chooses side)"}</Text>
      <TextInput style={styles.input} keyboardType="numbers-and-punctuation" value={offset} onChangeText={setOffset} />
      <View style={styles.row}>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.muted}>{ru ? "Толщина, мм" : "Thickness, mm"}</Text>
          <TextInput style={styles.input} keyboardType="decimal-pad" value={thickness} onChangeText={setThickness} />
        </View>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.muted}>{ru ? "Высота, мм" : "Height, mm"}</Text>
          <TextInput style={styles.input} keyboardType="decimal-pad" value={height} onChangeText={setHeight} />
        </View>
      </View>
      <Text style={styles.muted}>{ru ? "Отделка стены" : "Wall finish"}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
        <Pressable style={[styles.chip, materialId === null && { borderColor: colors.selection }]} onPress={() => setMaterialId(null)}>
          <Text style={[styles.chipText, materialId === null && { color: colors.selection }]}>{ru ? "Без отделки" : "No finish"}</Text>
        </Pressable>
        {wallMaterials.map((material) => (
          <Pressable
            key={material.id}
            style={[styles.chip, materialId === material.id && { borderColor: colors.selection }]}
            onPress={() => setMaterialId(material.id)}
          >
            <View style={{ width: 12, height: 12, borderRadius: 6, backgroundColor: material.base_color }} />
            <Text style={[styles.chipText, materialId === material.id && { color: colors.selection }]}>
              {ru ? material.name_ru : material.name}
            </Text>
          </Pressable>
        ))}
      </ScrollView>
      <Pressable
        accessibilityRole="button"
        style={[styles.button, styles.buttonPrimary, (!valid || busy) && { opacity: 0.5 }]}
        disabled={!valid || busy}
        onPress={() => onSubmit({ wallIndex, offsetMm, thicknessMm, heightMm, materialId })}
      >
        <Text style={styles.buttonText}>{ru ? "Перестроить комнату" : "Rebuild room"}</Text>
      </Pressable>
    </View>
  );
}
