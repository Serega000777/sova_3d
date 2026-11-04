import type {
  FacadeEdit,
  FacadeVariant,
  PhysicalAiClient,
  Version,
} from "@physical-ai/contracts";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Pressable, Text, View } from "react-native";

import {
  facadeVariantCompatibility,
  verifiedAppliedFacadeVariant,
} from "./facade-design-variants";
import { colors, radii, styles } from "./theme";

const MAX_VISIBLE_VARIANTS = 12;

export function FacadeDesignVariantsCard({
  client,
  projectId,
  activeVersionId,
  request,
  language,
  onApplied,
}: {
  client: PhysicalAiClient;
  projectId: string;
  activeVersionId: string;
  request: FacadeEdit;
  language: "ru" | "en";
  onApplied: (version: Version, variant: FacadeVariant, sourceVersionId: string) => void;
}) {
  const ru = language === "ru";
  const [variants, setVariants] = useState<FacadeVariant[]>([]);
  const [busy, setBusy] = useState<"load" | string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy("load");
    setError(null);
    try {
      setVariants(await client.listFacadeVariants(projectId));
    } catch (reason) {
      setVariants([]);
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }, [client, projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleVariants = useMemo(
    () => variants.slice(0, MAX_VISIBLE_VARIANTS),
    [variants],
  );

  async function apply(variant: FacadeVariant) {
    const sourceVersionId = activeVersionId;
    setBusy(variant.version_id);
    setError(null);
    setNotice(null);
    try {
      const accepted = await client.applyFacadeVariant(sourceVersionId, {
        variant_version_id: variant.version_id,
      });
      const job = await client.waitForJob(accepted.job_id);
      const versionId = (job.result as { version_id?: unknown } | null)?.version_id;
      if (typeof versionId !== "string") {
        throw new Error(ru ? "Сервер не вернул новую версию фасада." : "The server did not return a new facade version.");
      }
      const version = await client.getVersion(versionId);
      if (!verifiedAppliedFacadeVariant(job, version, sourceVersionId, variant)) {
        throw new Error(ru ? "Результат варианта не совпал с выбранной версией." : "The variant result did not match the selected version.");
      }
      onApplied(version, variant, sourceVersionId);
      setNotice(ru
        ? `«${variant.name}» сохранён как новая неизменяемая версия.`
        : `“${variant.name}” was saved as a new immutable version.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  return (
    <View
      style={[styles.card, { gap: 10, borderColor: colors.accent }]}
      accessibilityLabel={ru ? "Сохранённые варианты дизайна фасада" : "Saved facade design variants"}
    >
      <View style={{ gap: 3 }}>
        <Text style={styles.heading}>{ru ? "Варианты дизайна" : "Design variants"}</Text>
        <Text style={styles.muted}>
          {ru
            ? "Реальные сохранённые наборы отделки этого фасада. Цвета, площади и смета приходят с сервера; применение создаёт новую версию."
            : "Real saved finish sets for this facade. Colours, areas and estimate come from the server; applying one creates a new version."}
        </Text>
      </View>

      {busy === "load" ? <Text style={styles.muted}>{ru ? "Загружаем варианты…" : "Loading variants…"}</Text> : null}
      {!busy && variants.length === 0 && !error ? (
        <Text style={styles.muted}>
          {ru
            ? "Сохранённых вариантов пока нет. Создайте именованный вариант в web Studio — здесь он появится без копирования или выдуманных стилей."
            : "No saved variants yet. Create a named variant in web Studio and it will appear here without copied or invented styles."}
        </Text>
      ) : null}

      {visibleVariants.map((variant) => {
        const compatibility = facadeVariantCompatibility(request, variant);
        const colours = [...new Set(variant.surface_assignments.map((item) => item.colour))];
        const applying = busy === variant.version_id;
        const disabled = busy !== null || compatibility === "incompatible" || variant.surface_assignments.length === 0;
        return (
          <View key={variant.version_id} style={[styles.card, { gap: 8, borderRadius: radii.compact }]}>
            <View style={[styles.row, { justifyContent: "space-between", alignItems: "flex-start" }]}>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.text}>{variant.name}</Text>
                <Text style={styles.sectionSubtitle}>v{variant.sequence_no}</Text>
              </View>
              <Text style={[
                styles.chipText,
                { color: compatibility === "incompatible" ? colors.yellow : colors.green },
              ]}>
                {compatibility === "compatible"
                  ? (ru ? "Совместим" : "Compatible")
                  : compatibility === "incompatible"
                    ? (ru ? "Другая геометрия" : "Different geometry")
                    : (ru ? "Проверит сервер" : "Server check")}
              </Text>
            </View>
            <View style={[styles.row, { flexWrap: "wrap" }]}>
              {colours.map((colour) => (
                <View
                  key={colour}
                  accessibilityLabel={`${ru ? "Цвет" : "Colour"} ${colour}`}
                  style={{ width: 30, height: 30, borderRadius: 8, borderWidth: 1, borderColor: colors.border, backgroundColor: colour }}
                />
              ))}
              {colours.length === 0 ? <Text style={styles.muted}>{ru ? "Отделка не назначена" : "No finish assigned"}</Text> : null}
            </View>
            <View style={[styles.row, { flexWrap: "wrap" }]}>
              <Text style={styles.mono}>{ru ? "Стены" : "Walls"}: {(variant.category_areas_m2.walls ?? 0).toFixed(2)} м²</Text>
              <Text style={styles.mono}>{ru ? "Крыша" : "Roof"}: {(variant.category_areas_m2.roof ?? 0).toFixed(2)} м²</Text>
              <Text style={styles.mono}>{ru ? "Проёмы" : "Openings"}: {(variant.category_areas_m2.opening_frames ?? 0).toFixed(2)} м²</Text>
            </View>
            <Text style={styles.muted}>
              {variant.estimated_cost != null && variant.currency
                ? `${ru ? "Смета" : "Estimate"}: ${variant.estimated_cost.toLocaleString(ru ? "ru-RU" : "en-US", { maximumFractionDigits: 2 })} ${variant.currency}`
                : (ru ? "Смета не рассчитана: вариант не содержит полного источника цены." : "No estimate: the variant has no complete price source.")}
            </Text>
            <Pressable
              accessibilityRole="button"
              style={[styles.button, styles.buttonPrimary, disabled && { opacity: 0.45 }]}
              disabled={disabled}
              onPress={() => void apply(variant)}
            >
              <Text style={styles.buttonText}>
                {applying
                  ? (ru ? "Применяем…" : "Applying…")
                  : (ru ? "Выбрать вариант" : "Choose variant")}
              </Text>
            </Pressable>
          </View>
        );
      })}

      {variants.length > MAX_VISIBLE_VARIANTS ? (
        <Text style={styles.muted}>
          {ru
            ? `Показаны ${MAX_VISIBLE_VARIANTS} последних из ${variants.length}.`
            : `Showing the latest ${MAX_VISIBLE_VARIANTS} of ${variants.length}.`}
        </Text>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {notice ? <Text style={[styles.muted, { color: colors.green }]}>{notice}</Text> : null}
      <Pressable style={styles.button} disabled={busy !== null} onPress={() => void load()}>
        <Text style={styles.buttonText}>{ru ? "Обновить варианты" : "Refresh variants"}</Text>
      </Pressable>
    </View>
  );
}
