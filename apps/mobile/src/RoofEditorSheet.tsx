import type { FacadeEdit } from "@physical-ai/contracts";
import { useEffect, useMemo, useState } from "react";
import { Modal, Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { colors, styles } from "@/src/theme";

type RoofKind = "flat" | "gable" | "hip";

export function RoofEditorSheet({
  visible,
  language,
  initial,
  lengthMm,
  widthMm,
  busy,
  onApply,
  onClose,
}: {
  visible: boolean;
  language: "ru" | "en";
  initial: FacadeEdit;
  lengthMm: number;
  widthMm: number;
  busy: boolean;
  onApply: (request: FacadeEdit) => void;
  onClose: () => void;
}) {
  const ru = language === "ru";
  const [kind, setKind] = useState<RoofKind>("gable");
  const [heightMm, setHeightMm] = useState(1200);
  const [overhangMm, setOverhangMm] = useState(300);

  useEffect(() => {
    if (!visible) return;
    setKind(initial.roof === "flat" || initial.roof === "hip" ? initial.roof : "gable");
    setHeightMm(initial.roof_height_mm ?? 1200);
    setOverhangMm(initial.overhang_mm ?? 300);
  }, [initial, visible]);

  const runMm = (Math.min(lengthMm, widthMm) + overhangMm * 2) / 2;
  const slopeDeg = useMemo(
    () => runMm > 0 ? Math.atan2(heightMm, runMm) * 180 / Math.PI : 0,
    [heightMm, runMm],
  );
  const valid = Number.isFinite(heightMm) && heightMm >= 200 && heightMm <= 5000
    && Number.isFinite(overhangMm) && overhangMm >= 0 && overhangMm <= 2000;

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <ScrollView style={{ flex: 1, backgroundColor: colors.bg }} contentContainerStyle={{ padding: 20, gap: 16 }}>
        <View style={[styles.row, { justifyContent: "space-between" }]}>
          <Text style={styles.heading}>{ru ? "Конструктор крыши" : "Roof builder"}</Text>
          <Pressable style={styles.chip} onPress={onClose}><Text style={styles.chipText}>{ru ? "Закрыть" : "Close"}</Text></Pressable>
        </View>
        <Text style={styles.muted}>
          {ru
            ? "Параметры перестраивают точную крышу и сохраняют новую неизменяемую версию дома."
            : "The parameters rebuild exact roof geometry and save a new immutable house version."}
        </Text>
        <View style={[styles.row, { flexWrap: "wrap" }]}>
          {(["gable", "flat", "hip"] as const).map((value) => (
            <Pressable
              key={value}
              style={[styles.button, kind === value && styles.buttonPrimary]}
              onPress={() => setKind(value)}
            >
              <Text style={styles.buttonText}>
                {value === "gable" ? (ru ? "Двускатная" : "Gable") : value === "flat" ? (ru ? "Плоская" : "Flat") : (ru ? "Вальмовая" : "Hip")}
              </Text>
            </Pressable>
          ))}
        </View>
        <Text style={styles.muted}>{ru ? "Высота конька, мм" : "Ridge height, mm"}</Text>
        <TextInput style={styles.input} keyboardType="decimal-pad" value={String(heightMm)} onChangeText={(value) => setHeightMm(Number(value.replace(",", ".")))} />
        <Text style={styles.muted}>{ru ? "Свес кровли, мм" : "Roof overhang, mm"}</Text>
        <TextInput style={styles.input} keyboardType="decimal-pad" value={String(overhangMm)} onChangeText={(value) => setOverhangMm(Number(value.replace(",", ".")))} />
        {kind !== "flat" && (
          <>
            <Text style={styles.muted}>{ru ? "Уклон скатов, °" : "Roof pitch, °"}</Text>
            <TextInput
              style={styles.input}
              keyboardType="decimal-pad"
              value={slopeDeg.toFixed(1)}
              onChangeText={(value) => {
                const angle = Number(value.replace(",", "."));
                setHeightMm(Math.max(200, Math.min(5000, Math.round(Math.tan(angle * Math.PI / 180) * runMm))));
              }}
            />
          </>
        )}
        <Pressable
          style={[styles.button, styles.buttonPrimary, (!valid || busy) && { opacity: 0.5 }]}
          disabled={!valid || busy}
          onPress={() => onApply({ ...initial, roof: kind, roof_height_mm: heightMm, overhang_mm: overhangMm })}
        >
          <Text style={styles.buttonText}>{ru ? "Применить крышу" : "Apply roof"}</Text>
        </Pressable>
      </ScrollView>
    </Modal>
  );
}
