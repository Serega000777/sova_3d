import type { ScannedFacadeBody } from "@physical-ai/contracts";
import { useState } from "react";
import { Modal, Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { colors, elevationHigh, radii, styles } from "@/src/theme";

type Opening = NonNullable<ScannedFacadeBody["openings"]>[number];
type Roof = ScannedFacadeBody["roof"];
const SIDES = ["front", "back", "left", "right"] as const;
const ROOFS: Roof[] = ["none", "flat", "gable", "shed", "hip"];
const COLOURS = ["#c9ced8", "#f2ebdd", "#9ca98f", "#b9684f", "#3f454b"];

function number(value: string): number {
  return Number(value.replace(",", "."));
}

export function ScannedFacadeSheet({
  visible,
  busy,
  language,
  onClose,
  onApply,
}: {
  visible: boolean;
  busy: boolean;
  language: "ru" | "en";
  onClose: () => void;
  onApply: (body: ScannedFacadeBody) => void;
}) {
  const ru = language === "ru";
  const [length, setLength] = useState("10000");
  const [width, setWidth] = useState("8000");
  const [floorHeight, setFloorHeight] = useState("3000");
  const [floors, setFloors] = useState("1");
  const [wall, setWall] = useState("250");
  const [roof, setRoof] = useState<Roof>("flat");
  const [roofHeight, setRoofHeight] = useState("1200");
  const [overhang, setOverhang] = useState("300");
  const [colour, setColour] = useState(COLOURS[0] as string);
  const [openings, setOpenings] = useState<Opening[]>([]);

  const addOpening = (kind: "window" | "door") => {
    const index = openings.length + 1;
    setOpenings((items) => [
      ...items,
      {
        opening_id: `${kind}-${index}`,
        kind,
        side: "front",
        center_mm: 2_000,
        width_mm: kind === "door" ? 900 : 1_200,
        height_mm: kind === "door" ? 2_100 : 1_400,
        sill_mm: kind === "door" ? 0 : 900,
      },
    ]);
  };
  const updateOpening = (index: number, patch: Partial<Opening>) => {
    setOpenings((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  };
  const values = {
    length: number(length),
    width: number(width),
    floorHeight: number(floorHeight),
    floors: number(floors),
    wall: number(wall),
    roofHeight: number(roofHeight),
    overhang: number(overhang),
  };
  const valid =
    values.length >= 2_000 && values.length <= 50_000
    && values.width >= 2_000 && values.width <= 50_000
    && values.floorHeight >= 2_200 && values.floorHeight <= 6_000
    && Number.isInteger(values.floors) && values.floors >= 1 && values.floors <= 3
    && values.wall >= 100 && values.wall <= 600
    && values.roofHeight >= 200 && values.roofHeight <= 5_000
    && values.overhang >= 0 && values.overhang <= 2_000
    && openings.every((opening) =>
      Number.isFinite(opening.center_mm)
      && Number.isFinite(opening.width_mm)
      && Number.isFinite(opening.height_mm)
      && Number.isFinite(opening.sill_mm ?? 0),
    );

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.55)" }}>
        <View style={{ maxHeight: "92%", backgroundColor: colors.panel, borderTopLeftRadius: radii.hero, borderTopRightRadius: radii.hero, ...elevationHigh }}>
          <ScrollView contentContainerStyle={{ padding: 18, gap: 12 }}>
            <Text style={styles.title}>{ru ? "Фасад по скану" : "Facade from scan"}</Text>
            <Text style={styles.muted}>
              {ru
                ? "Введите измеренные размеры и проёмы. Скан остаётся исходником, а новая версия становится чистой точной оболочкой с семантическими стенами, крышей и проёмами."
                : "Enter measured dimensions and openings. The scan remains the source while a new version becomes a clean exact shell with semantic walls, roof and openings."}
            </Text>
            <View style={styles.row}>
              {([[ru ? "Длина" : "Length", length, setLength], [ru ? "Ширина" : "Width", width, setWidth]] as const).map(([label, value, setter]) => (
                <View key={label} style={{ flex: 1, gap: 4 }}>
                  <Text style={styles.muted}>{label}, {ru ? "мм" : "mm"}</Text>
                  <TextInput style={styles.input} keyboardType="decimal-pad" value={value} onChangeText={setter} />
                </View>
              ))}
            </View>
            <View style={styles.row}>
              {([[ru ? "Высота этажа" : "Floor height", floorHeight, setFloorHeight], [ru ? "Этажей" : "Floors", floors, setFloors], [ru ? "Стена" : "Wall", wall, setWall]] as const).map(([label, value, setter]) => (
                <View key={label} style={{ flex: 1, gap: 4 }}>
                  <Text style={styles.muted}>{label}</Text>
                  <TextInput style={styles.input} keyboardType="decimal-pad" value={value} onChangeText={setter} />
                </View>
              ))}
            </View>
            <Text style={styles.muted}>{ru ? "Крыша" : "Roof"}</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
              {ROOFS.map((item) => (
                <Pressable key={item} style={[styles.chip, roof === item && { borderColor: colors.selection }]} onPress={() => setRoof(item)}>
                  <Text style={[styles.chipText, roof === item && { color: colors.selection }]}>{item}</Text>
                </Pressable>
              ))}
            </ScrollView>
            {roof !== "none" && (
              <View style={styles.row}>
                <View style={{ flex: 1, gap: 4 }}><Text style={styles.muted}>{ru ? "Высота крыши, мм" : "Roof height, mm"}</Text><TextInput style={styles.input} keyboardType="decimal-pad" value={roofHeight} onChangeText={setRoofHeight} /></View>
                <View style={{ flex: 1, gap: 4 }}><Text style={styles.muted}>{ru ? "Свес, мм" : "Overhang, mm"}</Text><TextInput style={styles.input} keyboardType="decimal-pad" value={overhang} onChangeText={setOverhang} /></View>
              </View>
            )}
            <Text style={styles.muted}>{ru ? "Цвет стен" : "Wall colour"}</Text>
            <View style={styles.row}>
              {COLOURS.map((item) => <Pressable key={item} accessibilityLabel={item} onPress={() => setColour(item)} style={{ width: 38, height: 38, borderRadius: 19, backgroundColor: item, borderWidth: colour === item ? 3 : 1, borderColor: colour === item ? colors.selection : colors.border }} />)}
            </View>
            <View style={[styles.row, { justifyContent: "space-between" }]}>
              <Text style={styles.heading}>{ru ? "Проёмы" : "Openings"}</Text>
              <View style={styles.row}>
                <Pressable style={styles.button} onPress={() => addOpening("window")}><Text style={styles.buttonText}>+ {ru ? "Окно" : "Window"}</Text></Pressable>
                <Pressable style={styles.button} onPress={() => addOpening("door")}><Text style={styles.buttonText}>+ {ru ? "Дверь" : "Door"}</Text></Pressable>
              </View>
            </View>
            {openings.map((opening, index) => (
              <View key={opening.opening_id ?? index} style={[styles.card, { gap: 8 }]}>
                <View style={[styles.row, { justifyContent: "space-between" }]}><Text style={styles.heading}>{opening.kind === "door" ? (ru ? "Дверь" : "Door") : (ru ? "Окно" : "Window")} {index + 1}</Text><Pressable onPress={() => setOpenings((items) => items.filter((_, itemIndex) => itemIndex !== index))}><Text style={styles.error}>{ru ? "Удалить" : "Remove"}</Text></Pressable></View>
                <ScrollView horizontal contentContainerStyle={{ gap: 6 }}>{SIDES.map((side) => <Pressable key={side} style={[styles.chip, opening.side === side && { borderColor: colors.selection }]} onPress={() => updateOpening(index, { side })}><Text style={styles.chipText}>{side}</Text></Pressable>)}</ScrollView>
                {(["center_mm", "width_mm", "height_mm", "sill_mm"] as const).map((field) => <View key={field} style={{ gap: 3 }}><Text style={styles.muted}>{field}</Text><TextInput style={styles.input} keyboardType="decimal-pad" value={String(opening[field] ?? 0)} onChangeText={(value) => updateOpening(index, { [field]: number(value) })} /></View>)}
              </View>
            ))}
            <Pressable style={[styles.button, styles.buttonPrimary, (!valid || busy) && { opacity: 0.5 }]} disabled={!valid || busy} onPress={() => onApply({ length_mm: values.length, width_mm: values.width, floor_height_mm: values.floorHeight, floors: values.floors, wall_thickness_mm: values.wall, roof, roof_height_mm: values.roofHeight, overhang_mm: values.overhang, wall_colour: colour, openings })}>
              <Text style={styles.buttonText}>{ru ? "Создать точный фасад" : "Create exact facade"}</Text>
            </Pressable>
            <Pressable style={styles.button} disabled={busy} onPress={onClose}><Text style={styles.buttonText}>{ru ? "Отмена" : "Cancel"}</Text></Pressable>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}
