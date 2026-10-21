import { ApiError, type Material, type PrintDiagnosis, type PrintSymptom, type PrinterProfile } from "@physical-ai/contracts";
import { useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Image, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { type PickedPhoto, pickPhotos, uploadPhoto } from "@/src/photo";
import { useSession } from "@/src/session";
import { colors, radii, styles } from "@/src/theme";

const SYMPTOMS: { id: PrintSymptom; label: string }[] = [
  { id: "stringing", label: "Нити" },
  { id: "warping", label: "Отрыв углов" },
  { id: "poor_adhesion", label: "Слабая адгезия" },
  { id: "elephant_foot", label: "Слоновья нога" },
  { id: "under_extrusion", label: "Недоэкструзия" },
  { id: "over_extrusion", label: "Переэкструзия" },
  { id: "poor_overhangs", label: "Провисания" },
  { id: "layer_shift", label: "Смещение слоя" },
  { id: "dimensions_off", label: "Размеры ушли" },
  { id: "clogging", label: "Засор" },
];

const SETTING_LABELS: Record<string, string> = {
  nozzle_offset_c: "Температура сопла",
  bed_offset_c: "Температура стола",
  retraction_mm: "Ретракт",
  flow_pct: "Поток",
  brim_mm: "Кайма",
  elephant_foot_mm: "Компенсация первого слоя",
  first_layer_speed_pct: "Скорость первого слоя",
};

function symptomLabel(id: string): string {
  return SYMPTOMS.find((item) => item.id === id)?.label ?? id;
}

export default function PrintDoctorScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { client, session } = useSession();
  const [profile, setProfile] = useState<PrinterProfile | null>(null);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [materialId, setMaterialId] = useState("pla");
  const [symptoms, setSymptoms] = useState<PrintSymptom[]>([]);
  const [photos, setPhotos] = useState<PickedPhoto[]>([]);
  const [diagnosis, setDiagnosis] = useState<PrintDiagnosis | null>(null);
  const [photoEvidence, setPhotoEvidence] = useState<{ symptom: string; evidence: string; confidence: number }[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client || !session || !id) return;
    try {
      const [profiles, stock] = await Promise.all([
        client.listPrinterProfiles(session.workspaceId),
        client.listMaterials(),
      ]);
      const current = profiles.find((item) => item.id === id) ?? null;
      setProfile(current);
      setMaterials(stock);
      setMaterialId(current?.default_material_id ?? stock[0]?.id ?? "pla");
      if (!current) setError("Профиль принтера не найден в текущем рабочем пространстве.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [client, id, session]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function addPhotos(source: "camera" | "library") {
    const next = await pickPhotos(source, 3 - photos.length);
    setPhotos((current) => [...current, ...next].slice(0, 3));
  }

  async function analyze() {
    if (!client || !session || !profile || busy || (symptoms.length === 0 && photos.length === 0)) return;
    setBusy(photos.length > 0 ? "ИИ анализирует фото…" : "Строим рекомендации…");
    setError(null);
    setDiagnosis(null);
    setPhotoEvidence([]);
    try {
      if (photos.length > 0) {
        const photoAssetIds: string[] = [];
        for (const photo of photos) photoAssetIds.push(await uploadPhoto(client, session.workspaceId, photo));
        const accepted = await client.reportPrintPhotos(profile.id, {
          material_id: materialId,
          outcome: "partial",
          symptoms,
          apply: false,
          photo_asset_ids: photoAssetIds,
        });
        const job = await client.waitForJob(accepted.job_id);
        if (job.status !== "succeeded") {
          const detail = job.error as { message?: string } | null;
          throw new Error(detail?.message ?? "Не удалось разобрать фотографии печати.");
        }
        const result = job.result as unknown as PrintDiagnosis & { photo?: { seen?: { symptom: string; evidence: string; confidence: number }[] } };
        setDiagnosis(result);
        setPhotoEvidence((result.photo?.seen ?? []).filter((item) => item.confidence >= 0.5));
      } else {
        setDiagnosis(await client.reportPrint(profile.id, {
          material_id: materialId,
          outcome: "partial",
          symptoms,
          apply: false,
        }));
      }
    } catch (err) {
      if (err instanceof ApiError && err.code === "photo_diagnosis_not_enabled") {
        setError("Фото-анализ сейчас не подключён. Выберите видимые дефекты вручную — проверенные правила продолжат работать без ИИ.");
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusy(null);
    }
  }

  async function applyRecommendations() {
    if (!client || !profile || !diagnosis || busy) return;
    const found = diagnosis.findings.map((finding) => finding.symptom);
    setBusy("Применяем к профилю…");
    setError(null);
    try {
      const applied = await client.reportPrint(profile.id, {
        material_id: materialId,
        outcome: "partial",
        symptoms: found,
        apply: true,
      });
      setDiagnosis(applied);
      setPhotos([]);
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
      <ScrollView contentContainerStyle={{ width: "100%", maxWidth: 900, alignSelf: "center", padding: 16, paddingBottom: 36, gap: 14 }}>
        <View style={{ gap: 5 }}>
          <Text style={[styles.title, { fontSize: 29 }]}>AI Print Doctor</Text>
          <Text style={styles.muted}>{profile?.name ?? "Принтер"} · диагностика результата печати</Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Материал</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
            {materials.map((material) => (
              <Pressable key={material.id} onPress={() => { setMaterialId(material.id); setDiagnosis(null); }} style={[styles.chip, materialId === material.id && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}>
                <Text style={styles.chipText}>{material.name}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>

        <View style={[styles.card, { borderRadius: radii.feature }]}>
          <Text style={styles.sectionTitle}>Фото результата</Text>
          <Text style={styles.muted}>До трёх фото. ИИ называет только распознанные симптомы; точной рамки дефекта и автоматического измерения пока нет.</Text>
          <View style={styles.row}>
            <Pressable disabled={photos.length >= 3 || Boolean(busy)} onPress={() => void addPhotos("camera")} style={styles.button}><Text style={styles.buttonText}>Камера</Text></Pressable>
            <Pressable disabled={photos.length >= 3 || Boolean(busy)} onPress={() => void addPhotos("library")} style={styles.button}><Text style={styles.buttonText}>Галерея</Text></Pressable>
            {photos.length > 0 ? <Pressable onPress={() => setPhotos([])} style={styles.button}><Text style={styles.buttonText}>Очистить</Text></Pressable> : null}
          </View>
          {photos.length > 0 ? <ScrollView horizontal contentContainerStyle={{ gap: 8 }}>{photos.map((photo, index) => <Image key={`${photo.uri}:${index}`} source={{ uri: photo.uri }} style={{ width: 116, height: 92, borderRadius: radii.preview, backgroundColor: colors.viewport }} />)}</ScrollView> : null}
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Видимые дефекты</Text>
          <Text style={styles.muted}>Выберите вручную как fallback или дополнение к фото.</Text>
          <View style={styles.row}>
            {SYMPTOMS.map((item) => {
              const selected = symptoms.includes(item.id);
              return <Pressable key={item.id} onPress={() => { setDiagnosis(null); setSymptoms((current) => selected ? current.filter((value) => value !== item.id) : [...current, item.id]); }} style={[styles.chip, selected && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}><Text style={styles.chipText}>{item.label}</Text></Pressable>;
            })}
          </View>
          <Pressable disabled={Boolean(busy) || !profile || (symptoms.length === 0 && photos.length === 0)} onPress={() => void analyze()} style={[styles.button, styles.buttonPrimary, (Boolean(busy) || !profile || (symptoms.length === 0 && photos.length === 0)) && { opacity: 0.45 }]}>
            <Text style={styles.buttonText}>{busy ?? "Получить рекомендации"}</Text>
          </Pressable>
        </View>

        {error ? <Text style={styles.error}>{error}</Text> : null}

        {diagnosis ? (
          <View style={[styles.card, { borderColor: diagnosis.applied ? colors.green : colors.yellow }]}>
            <Text style={styles.sectionTitle}>{diagnosis.applied ? "Рекомендации применены" : "Предпросмотр рекомендаций"}</Text>
            {photoEvidence.map((item) => <Text key={`${item.symptom}:${item.evidence}`} style={styles.muted}>Фото: {symptomLabel(item.symptom)} — {item.evidence} ({Math.round(item.confidence * 100)}%)</Text>)}
            {diagnosis.findings.map((finding) => (
              <View key={finding.symptom} style={{ gap: 6, paddingVertical: 9, borderTopWidth: 1, borderTopColor: colors.border }}>
                <Text style={styles.heading}>{symptomLabel(finding.symptom)}</Text>
                <Text style={styles.muted}>Возможная причина: {finding.causes.join("; ")}</Text>
                {finding.changes.length > 0 ? finding.changes.map((change) => <Text key={change.setting} style={{ color: colors.yellow }}>{SETTING_LABELS[change.setting] ?? change.setting}: {change.before} → {change.after}</Text>) : <Text style={styles.muted}>Настройки автоматически не меняются: нужна механическая проверка или калибровка.</Text>}
                <Text style={styles.muted}>{finding.advice}</Text>
              </View>
            ))}
            {!diagnosis.applied && diagnosis.findings.length > 0 ? <Pressable disabled={Boolean(busy)} onPress={() => void applyRecommendations()} style={[styles.button, styles.buttonPrimary]}><Text style={styles.buttonText}>{busy ?? "Применить к следующей печати"}</Text></Pressable> : null}
            <Text style={styles.sectionSubtitle}>Изменения влияют только на будущий слайсинг этого материала и принтера. Текущую деталь, модель или уже созданный G-code они не исправляют.</Text>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
