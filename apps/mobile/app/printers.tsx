import type { Material, PrinterModel, PrinterProfile } from "@physical-ai/contracts";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  type ToolChangeDraft,
  type ValidToolChangeConfig,
  nextAvailableMaterialSlot,
  validateToolChangeConfig,
} from "@/src/printer-tool-change";
import { useSession } from "@/src/session";
import { colors, elevationLow, radii, styles } from "@/src/theme";

function modelLabel(model: PrinterModel | undefined, fallback: string): string {
  return model ? `${model.vendor} ${model.model}` : fallback;
}

function RaftDensityEditor({
  profile,
  materials,
  disabled,
  onSave,
}: {
  profile: PrinterProfile;
  materials: Material[];
  disabled: boolean;
  onSave: (materialId: string, base: number, face: number) => Promise<void>;
}) {
  const [selected, setSelected] = useState(profile.default_material_id ?? materials[0]?.id ?? "");
  const initial = profile.raft_density_profiles[selected];
  const [base, setBase] = useState(String(initial?.base_density_pct ?? 40));
  const [face, setFace] = useState(String(initial?.interface_density_pct ?? 100));
  function choose(materialId: string) {
    setSelected(materialId);
    setBase(String(profile.raft_density_profiles[materialId]?.base_density_pct ?? 40));
    setFace(String(profile.raft_density_profiles[materialId]?.interface_density_pct ?? 100));
  }
  const baseNumber = Number(base.replace(",", "."));
  const faceNumber = Number(face.replace(",", "."));
  const valid = selected && baseNumber >= 10 && baseNumber <= 70 && faceNumber >= 50 && faceNumber <= 100;
  return (
    <View style={{ gap: 8 }}>
      <Text style={styles.sectionSubtitle}>Плотность рафта по материалу</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
        {materials.map((material) => (
          <Pressable key={material.id} onPress={() => choose(material.id)} style={[styles.chip, selected === material.id && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}>
            <Text style={styles.chipText}>{material.name}</Text>
          </Pressable>
        ))}
      </ScrollView>
      <View style={styles.row}>
        <TextInput accessibilityLabel="Плотность основы рафта" keyboardType="decimal-pad" value={base} onChangeText={setBase} style={[styles.input, { flex: 1 }]} placeholder="Основа 10–70%" placeholderTextColor={colors.muted} />
        <TextInput accessibilityLabel="Плотность интерфейса рафта" keyboardType="decimal-pad" value={face} onChangeText={setFace} style={[styles.input, { flex: 1 }]} placeholder="Интерфейс 50–100%" placeholderTextColor={colors.muted} />
      </View>
      <Text style={styles.muted}>Без настройки сохраняется прежний шаг: основа 40%, интерфейс 100%.</Text>
      <Pressable disabled={disabled || !valid} onPress={() => void onSave(selected, baseNumber, faceNumber)} style={[styles.button, (disabled || !valid) && { opacity: 0.45 }]}>
        <Text style={styles.buttonText}>Сохранить пару</Text>
      </Pressable>
    </View>
  );
}

function numericInput(value: string): number {
  return value.trim() ? Number(value.replace(",", ".")) : Number.NaN;
}

function profileToolChangeDraft(profile: PrinterProfile): ToolChangeDraft {
  return {
    tool_change_mode: profile.tool_change_mode === "marlin_tn" ? "marlin_tn" : "disabled",
    tool_count: profile.tool_count,
    base_tool: profile.base_tool,
    purge_tower_enabled: profile.purge_tower_enabled,
    purge_tower_width_mm: Number(profile.purge_tower_width_mm),
    purge_volume_mm3: Number(profile.purge_volume_mm3),
    material_slots: profile.material_slots.map((item) => ({ ...item })),
  };
}

function ToolChangeEditor({
  profile,
  materials,
  disabled,
  saving,
  onSave,
}: {
  profile: PrinterProfile;
  materials: Material[];
  disabled: boolean;
  saving: boolean;
  onSave: (config: ValidToolChangeConfig) => Promise<void>;
}) {
  const initial = profileToolChangeDraft(profile);
  const [mode, setMode] = useState(initial.tool_change_mode);
  const [toolCount, setToolCount] = useState(String(initial.tool_count));
  const [baseTool, setBaseTool] = useState(String(initial.base_tool));
  const [purgeEnabled, setPurgeEnabled] = useState(initial.purge_tower_enabled);
  const [purgeWidth, setPurgeWidth] = useState(String(initial.purge_tower_width_mm));
  const [purgeVolume, setPurgeVolume] = useState(String(initial.purge_volume_mm3));
  const [slots, setSlots] = useState(initial.material_slots);

  useEffect(() => {
    const next = profileToolChangeDraft(profile);
    setMode(next.tool_change_mode);
    setToolCount(String(next.tool_count));
    setBaseTool(String(next.base_tool));
    setPurgeEnabled(next.purge_tower_enabled);
    setPurgeWidth(String(next.purge_tower_width_mm));
    setPurgeVolume(String(next.purge_volume_mm3));
    setSlots(next.material_slots);
  }, [profile]);

  const draft: ToolChangeDraft = {
    tool_change_mode: mode,
    tool_count: numericInput(toolCount),
    base_tool: numericInput(baseTool),
    purge_tower_enabled: purgeEnabled,
    purge_tower_width_mm: numericInput(purgeWidth),
    purge_volume_mm3: numericInput(purgeVolume),
    material_slots: slots,
  };
  const validation = validateToolChangeConfig(
    draft,
    materials.map((material) => material.id),
    profile.default_material_id,
  );
  const nextFreeSlot = nextAvailableMaterialSlot(mode, draft.tool_count, slots);
  const fallbackMaterialId = profile.default_material_id ?? materials[0]?.id;

  function setSlot(index: number, patch: Partial<(typeof slots)[number]>) {
    setSlots((current) => current.map((item, itemIndex) => (
      itemIndex === index ? { ...item, ...patch } : item
    )));
  }

  return (
    <View style={{ gap: 8 }}>
      <Text style={styles.sectionSubtitle}>Multi-material capability и загруженные слоты</Text>
      <View style={styles.row}>
        <Pressable
          disabled={disabled}
          onPress={() => {
            setMode("disabled");
            setPurgeEnabled(false);
          }}
          style={[styles.chip, mode === "disabled" && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}
        >
          <Text style={styles.chipText}>Отключено / только инвентарь</Text>
        </Pressable>
        <Pressable
          disabled={disabled}
          onPress={() => setMode("marlin_tn")}
          style={[styles.chip, mode === "marlin_tn" && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}
        >
          <Text style={styles.chipText}>Generic Marlin Tn</Text>
        </Pressable>
      </View>
      <View style={styles.row}>
        <TextInput
          accessibilityLabel="Количество инструментов"
          editable={!disabled}
          keyboardType="number-pad"
          value={toolCount}
          onChangeText={setToolCount}
          style={[styles.input, { flex: 1, minWidth: 150 }]}
          placeholder="Инструментов 1–16"
          placeholderTextColor={colors.muted}
        />
        <TextInput
          accessibilityLabel="Базовый инструмент"
          editable={!disabled}
          keyboardType="number-pad"
          value={baseTool}
          onChangeText={setBaseTool}
          style={[styles.input, { flex: 1, minWidth: 150 }]}
          placeholder="Базовый Tn"
          placeholderTextColor={colors.muted}
        />
      </View>
      <Pressable
        disabled={disabled || mode === "disabled"}
        onPress={() => setPurgeEnabled((current) => !current)}
        style={[styles.button, mode === "disabled" && { opacity: 0.45 }]}
      >
        <Text style={styles.buttonText}>Purge-башня: {purgeEnabled ? "включена" : "выключена"}</Text>
      </Pressable>
      <View style={styles.row}>
        <TextInput
          accessibilityLabel="Ширина purge-башни"
          editable={!disabled}
          keyboardType="decimal-pad"
          value={purgeWidth}
          onChangeText={setPurgeWidth}
          style={[styles.input, { flex: 1, minWidth: 150 }]}
          placeholder="Ширина 10–40 мм"
          placeholderTextColor={colors.muted}
        />
        <TextInput
          accessibilityLabel="Purge на переход"
          editable={!disabled}
          keyboardType="decimal-pad"
          value={purgeVolume}
          onChangeText={setPurgeVolume}
          style={[styles.input, { flex: 1, minWidth: 150 }]}
          placeholder="Объём 10–500 мм³"
          placeholderTextColor={colors.muted}
        />
      </View>
      <Text style={styles.sectionSubtitle}>Загруженные слоты</Text>
      {slots.map((item, index) => (
        <View key={String(index) + "-" + item.slot} style={{ gap: 7, padding: 10, borderWidth: 1, borderColor: colors.border, borderRadius: radii.compact }}>
          <View style={styles.row}>
            <TextInput
              accessibilityLabel={"Номер загруженного слота " + (index + 1)}
              editable={!disabled}
              keyboardType="number-pad"
              value={Number.isNaN(item.slot) ? "" : String(item.slot)}
              onChangeText={(value) => setSlot(index, { slot: numericInput(value) })}
              style={[styles.input, { width: 90 }]}
              placeholder="Tn"
              placeholderTextColor={colors.muted}
            />
            <Pressable disabled={disabled} onPress={() => setSlots((current) => current.filter((_, itemIndex) => itemIndex !== index))} style={[styles.button, { flex: 1 }]}>
              <Text style={styles.buttonText}>Удалить T{item.slot}</Text>
            </Pressable>
          </View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
            {materials.map((material) => (
              <Pressable
                key={material.id}
                disabled={disabled}
                onPress={() => setSlot(index, { material_id: material.id })}
                style={[styles.chip, item.material_id === material.id && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}
              >
                <Text style={styles.chipText}>{material.name}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>
      ))}
      <Pressable
        disabled={disabled || nextFreeSlot == null || !fallbackMaterialId}
        onPress={() => {
          if (nextFreeSlot != null && fallbackMaterialId) {
            setSlots((current) => [...current, { slot: nextFreeSlot, material_id: fallbackMaterialId }]);
          }
        }}
        style={[styles.button, (disabled || nextFreeSlot == null || !fallbackMaterialId) && { opacity: 0.45 }]}
      >
        <Text style={styles.buttonText}>Добавить загруженный слот</Text>
      </Pressable>
      {!validation.ok ? <Text style={styles.error}>{validation.error}</Text> : null}
      <Text style={styles.muted}>
        Инвентарь слотов сам по себе не включает переключение. Поддерживается только generic Marlin Tn,
        где слот N — физический Tn; AMS/MMU и vendor macros не поддерживаются, приёмка на физическом
        оборудовании не выполнена.
      </Text>
      <Pressable
        disabled={disabled || !validation.ok}
        onPress={() => {
          if (validation.ok) void onSave(validation.value);
        }}
        style={[styles.button, styles.buttonPrimary, (disabled || !validation.ok) && { opacity: 0.45 }]}
      >
        <Text style={styles.buttonText}>{saving ? "Сохраняем…" : "Сохранить capability и слоты"}</Text>
      </Pressable>
    </View>
  );
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

  async function saveRaftDensity(profile: PrinterProfile, selectedMaterialId: string, base: number, face: number) {
    if (!client || busy) return;
    setBusy(profile.id);
    setError(null);
    try {
      await client.updatePrinterProfile(profile.id, {
        raft_density_profiles: {
          ...profile.raft_density_profiles,
          [selectedMaterialId]: { base_density_pct: base, interface_density_pct: face },
        },
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function saveToolChange(profile: PrinterProfile, config: ValidToolChangeConfig) {
    if (!client || busy) return;
    setBusy(profile.id);
    setError(null);
    try {
      await client.updatePrinterProfile(profile.id, {
        tool_change_mode: config.tool_change_mode,
        tool_count: config.tool_count,
        base_tool: config.base_tool,
        purge_tower_enabled: config.purge_tower_enabled,
        purge_tower_width_mm: config.purge_tower_width_mm,
        purge_volume_mm3: config.purge_volume_mm3,
        material_slots: config.material_slots,
      });
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
        <Pressable onPress={() => router.push("/print-queue")} style={[styles.button, styles.buttonPrimary]}>
          <Text style={styles.buttonText}>Спланировать очередь печати</Text>
        </Pressable>

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
                  <Text style={[styles.statusText, { color: profile.is_default ? colors.green : colors.muted }]}>{profile.is_default ? "По умолчанию" : "Профиль"}</Text>
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
                <View style={{ flex: 1, minWidth: 180, backgroundColor: colors.panel2, borderRadius: radii.compact, padding: 11, gap: 3 }}>
                  <Text style={styles.sectionSubtitle}>Рабочий объём</Text>
                  <Text style={styles.heading}>
                    {model ? `${model.bed_x_mm} × ${model.bed_y_mm} × ${model.bed_z_mm} мм` : "Неизвестен"}
                  </Text>
                </View>
              </View>
              {!profile.is_default ? (
                <Pressable disabled={Boolean(busy)} onPress={() => void makeDefault(profile)} style={[styles.button, busy === profile.id && { opacity: 0.5 }]}>
                  <Text style={styles.buttonText}>{busy === profile.id ? "Сохраняем…" : "Использовать по умолчанию"}</Text>
                </Pressable>
              ) : null}
              <RaftDensityEditor
                profile={profile}
                materials={materials}
                disabled={busy === profile.id}
                onSave={(selectedMaterialId, base, face) => saveRaftDensity(profile, selectedMaterialId, base, face)}
              />
              <ToolChangeEditor
                profile={profile}
                materials={materials}
                disabled={Boolean(busy)}
                saving={busy === profile.id}
                onSave={(config) => saveToolChange(profile, config)}
              />
              <Pressable onPress={() => router.push(`/printer-calibration/${profile.id}`)} style={[styles.button, { borderColor: colors.accent }]}>
                <Text style={[styles.buttonText, { color: colors.accent }]}>Калибровать принтер</Text>
              </Pressable>
              <Pressable onPress={() => router.push(`/print-monitor/${profile.id}`)} style={[styles.button, { borderColor: colors.accent }]}>
                <Text style={[styles.buttonText, { color: colors.accent }]}>Контроль печати</Text>
              </Pressable>
              <Pressable onPress={() => router.push(`/print-doctor/${profile.id}`)} style={styles.button}>
                <Text style={styles.buttonText}>AI Print Doctor</Text>
              </Pressable>
            </View>
          );
        })}
      </ScrollView>
    </SafeAreaView>
  );
}
