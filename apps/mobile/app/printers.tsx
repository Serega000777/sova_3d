import type { Material, PrinterModel, PrinterProfile } from "@physical-ai/contracts";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/src/session";
import { colors, elevationLow, radii, styles } from "@/src/theme";

function modelLabel(model: PrinterModel | undefined, fallback: string): string {
  return model ? `${model.vendor} ${model.model}` : fallback;
}

export default function PrintersScreen() {
  const router = useRouter();
  const { client, session } = useSession();
  const [profiles, setProfiles] = useState<PrinterProfile[]>([]);
  const [models, setModels] = useState<PrinterModel[]>([]);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState("");
  const [materialId, setMaterialId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const modelById = useMemo(() => new Map(models.map((model) => [model.id, model])), [models]);
  const materialById = useMemo(() => new Map(materials.map((material) => [material.id, material])), [materials]);

  const refresh = useCallback(async () => {
    if (!client || !session) return;
    setError(null);
    try {
      const [nextProfiles, nextModels, nextMaterials] = await Promise.all([
        client.listPrinterProfiles(session.workspaceId),
        client.listPrinterModels(),
        client.listMaterials(),
      ]);
      setProfiles(nextProfiles);
      setModels(nextModels);
      setMaterials(nextMaterials);
      setModelId((current) => current || nextModels[0]?.id || "");
      setMaterialId((current) => current || nextMaterials[0]?.id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [client, session]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function createProfile() {
    if (!client || !session || !name.trim() || !modelId || busy) return;
    setBusy("create");
    setError(null);
    try {
      await client.createPrinterProfile({
        workspace_id: session.workspaceId,
        printer_model_id: modelId,
        name: name.trim(),
        default_material_id: materialId || null,
        is_default: profiles.length === 0,
      });
      setName("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function makeDefault(profile: PrinterProfile) {
    if (!client || busy) return;
    setBusy(profile.id);
    setError(null);
    try {
      await client.updatePrinterProfile(profile.id, { is_default: true });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return <View style={[styles.screen, { alignItems: "center", justifyContent: "center" }]}><ActivityIndicator color={colors.accent} /></View>;
  }

  return (
    <SafeAreaView style={styles.screen} edges={["bottom"]}>
      <ScrollView contentContainerStyle={{ width: "100%", maxWidth: 820, alignSelf: "center", padding: 16, paddingBottom: 32, gap: 14 }}>
        <View style={{ gap: 5 }}>
          <Text style={[styles.title, { fontSize: 29 }]}>Профили принтеров</Text>
          <Text style={styles.muted}>Реальные размеры стола, сопла и материала используются анализом и подготовкой печати.</Text>
        </View>

        <View style={[styles.card, { borderRadius: radii.section }]}>
          <Text style={styles.sectionTitle}>Добавить принтер</Text>
          <TextInput
            accessibilityLabel="Название профиля принтера"
            placeholder="Название, например Принтер в мастерской"
            placeholderTextColor={colors.muted}
            value={name}
            onChangeText={setName}
            style={styles.input}
          />
          <Text style={styles.sectionSubtitle}>Модель</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
            {models.map((model) => (
              <Pressable key={model.id} onPress={() => setModelId(model.id)} style={[styles.chip, modelId === model.id && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}>
                <Text style={styles.chipText}>{modelLabel(model, model.id)}</Text>
              </Pressable>
            ))}
          </ScrollView>
          <Text style={styles.sectionSubtitle}>Материал по умолчанию</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
            {materials.map((material) => (
              <Pressable key={material.id} onPress={() => setMaterialId(material.id)} style={[styles.chip, materialId === material.id && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}>
                <Text style={styles.chipText}>{material.name}</Text>
              </Pressable>
            ))}
          </ScrollView>
          <Pressable disabled={!name.trim() || !modelId || Boolean(busy)} onPress={() => void createProfile()} style={[styles.button, styles.buttonPrimary, (!name.trim() || !modelId || Boolean(busy)) && { opacity: 0.45 }]}>
            <Text style={styles.buttonText}>{busy === "create" ? "Добавляем…" : "Добавить профиль"}</Text>
          </Pressable>
        </View>

        {error ? <Text style={styles.error}>{error}</Text> : null}

        {profiles.length === 0 ? (
          <View style={styles.card}>
            <Text style={styles.heading}>Профилей пока нет</Text>
            <Text style={styles.muted}>Добавьте конкретный принтер, чтобы не готовить модель по усреднённым параметрам.</Text>
          </View>
        ) : profiles.map((profile) => {
          const model = modelById.get(profile.printer_model_id);
          const material = profile.default_material_id ? materialById.get(profile.default_material_id) : undefined;
          const nozzle = profile.nozzle_mm ?? model?.nozzle_mm;
          return (
            <View key={profile.id} style={[styles.card, { borderRadius: radii.feature, ...elevationLow }]}>
              <View style={[styles.row, { justifyContent: "space-between" }]}>
                <View style={{ flex: 1, gap: 3 }}>
                  <Text style={styles.sectionTitle}>{profile.name}</Text>
                  <Text style={styles.muted}>{modelLabel(model, profile.printer_model_id)}</Text>
                </View>
                <View style={[styles.statusBadge, { backgroundColor: profile.is_default ? colors.greenWash : colors.panel2 }]}>
                  <View style={[styles.statusDot, { backgroundColor: profile.is_default ? colors.green : colors.muted }]} />
                  <Text style={[styles.statusText, { color: profile.is_default ? colors.green : colors.muted }]}>{profile.is_default ? "По умолчанию" : "Готов"}</Text>
                </View>
              </View>
              <View style={[styles.row, { alignItems: "stretch" }]}>
                <View style={{ flex: 1, minWidth: 110, backgroundColor: colors.panel2, borderRadius: radii.compact, padding: 11, gap: 3 }}>
                  <Text style={styles.sectionSubtitle}>Сопло</Text>
                  <Text style={styles.heading}>{nozzle != null ? `${nozzle} мм` : "Не задано"}</Text>
                </View>
                <View style={{ flex: 1, minWidth: 110, backgroundColor: colors.panel2, borderRadius: radii.compact, padding: 11, gap: 3 }}>
                  <Text style={styles.sectionSubtitle}>Материал</Text>
                  <Text style={styles.heading}>{material?.name ?? profile.default_material_id?.toUpperCase() ?? "Не задан"}</Text>
                </View>
                <View style={{ flex: 1, minWidth: 110, backgroundColor: colors.panel2, borderRadius: radii.compact, padding: 11, gap: 3 }}>
                  <Text style={styles.sectionSubtitle}>Слой</Text>
                  <Text style={styles.heading}>{profile.layer_height_mm} мм</Text>
                </View>
              </View>
              {!profile.is_default ? (
                <Pressable disabled={Boolean(busy)} onPress={() => void makeDefault(profile)} style={[styles.button, busy === profile.id && { opacity: 0.5 }]}>
                  <Text style={styles.buttonText}>{busy === profile.id ? "Сохраняем…" : "Использовать по умолчанию"}</Text>
                </Pressable>
              ) : null}
              <Pressable onPress={() => router.push(`/printer-calibration/${profile.id}`)} style={[styles.button, { borderColor: colors.accent }]}>
                <Text style={[styles.buttonText, { color: colors.accent }]}>Калибровать принтер</Text>
              </Pressable>
            </View>
          );
        })}
      </ScrollView>
    </SafeAreaView>
  );
}
