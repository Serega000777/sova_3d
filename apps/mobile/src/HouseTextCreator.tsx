import {
  ApiError,
  houseTextApplyBody,
  houseTextRefusal,
  houseTextRows,
  type HouseTextProposal,
  type PhysicalAiClient,
} from "@physical-ai/contracts";
import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { colors, styles } from "./theme";

const EXAMPLES = [
  "Создай двухэтажный прямоугольный дом 12 × 8 м, высота этажа 3 м",
  "Построй дом длиной 10 м и шириной 9 м, 1 этаж, высота этажа 280 см",
] as const;

function describe(reason: unknown): string {
  if (reason instanceof ApiError) return houseTextRefusal(reason.details, reason.message, "ru");
  return reason instanceof Error ? reason.message : String(reason);
}

/** Item 41: mobile description → read-only proposal → explicit apply → immutable house job. */
export function HouseTextCreator({
  client,
  workspaceId,
  onCreated,
  onBack,
}: {
  client: PhysicalAiClient;
  workspaceId: string;
  onCreated: (projectId: string) => void;
  onBack: () => void;
}) {
  const [text, setText] = useState("");
  const [proposal, setProposal] = useState<HouseTextProposal | null>(null);
  const [proposedText, setProposedText] = useState<string | null>(null);
  const [busy, setBusy] = useState<"propose" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);

  function edit(value: string) {
    setText(value);
    // The server proposal belongs to the exact original string. Any edit invalidates it.
    setProposal(null);
    setProposedText(null);
    setError(null);
  }

  async function propose() {
    const prompt = text.trim();
    if (!prompt || busy) return;
    setBusy("propose");
    setError(null);
    try {
      const next = await client.proposeHouseFromText({ workspace_id: workspaceId, prompt });
      setProposal(next);
      setProposedText(prompt);
    } catch (reason) {
      setProposal(null);
      setProposedText(null);
      setError(describe(reason));
    } finally {
      setBusy(null);
    }
  }

  async function apply() {
    if (!proposal || proposedText === null || busy) return;
    setBusy("apply");
    setError(null);
    try {
      const accepted = await client.applyHouseFromText(
        houseTextApplyBody(proposal, proposedText),
        `mobile-house-text-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      );
      const job = await client.waitForJob(accepted.job.job_id, { intervalMs: 1_000 });
      if (job.status !== "succeeded") {
        throw new Error((job.error as { message?: string } | null)?.message ?? "Дом не построен");
      }
      onCreated(accepted.project_id);
    } catch (reason) {
      setError(describe(reason));
      setBusy(null);
    }
  }

  function cancel() {
    setProposal(null);
    setProposedText(null);
    setError(null);
  }

  return (
    <View style={{ gap: 12 }}>
      <View style={{ gap: 4 }}>
        <Text style={styles.heading}>Дом по описанию</Text>
        <Text style={styles.muted}>
          Укажите размеры с единицами, высоту этажа и число этажей. До подтверждения задача не
          создаётся и AI не используется.
        </Text>
      </View>

      <TextInput
        style={[styles.input, { minHeight: 104, textAlignVertical: "top" }]}
        value={text}
        onChangeText={edit}
        editable={busy === null}
        multiline
        maxLength={500}
        placeholder={EXAMPLES[0]}
        placeholderTextColor={colors.muted}
        accessibilityLabel="Описание дома"
      />

      <View style={styles.row}>
        {EXAMPLES.map((example, index) => (
          <Pressable
            key={example}
            style={[styles.chip, { flexShrink: 1 }]}
            disabled={busy !== null}
            onPress={() => edit(example)}
          >
            <Text style={styles.chipText}>Пример {index + 1}</Text>
          </Pressable>
        ))}
      </View>

      <Text style={styles.muted}>
        Поддерживается один прямоугольный дом без лестниц, крыши, окон и комнат. Эти элементы можно
        добавить позже в редакторе.
      </Text>

      {proposal ? (
        <View
          style={[
            styles.card,
            { backgroundColor: colors.accentWash, borderColor: colors.accent },
          ]}
          accessibilityLiveRegion="polite"
        >
          <Text style={styles.heading}>Проверьте предложение</Text>
          <Text style={styles.text}>{proposal.summary_ru}</Text>
          {houseTextRows(proposal, "ru").map((row) => (
            <View
              key={row.field}
              style={[styles.row, { justifyContent: "space-between", alignItems: "flex-start" }]}
            >
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.muted}>{row.label}</Text>
                {row.source ? <Text style={styles.sectionSubtitle}>«{row.source}»</Text> : null}
              </View>
              <Text style={[styles.heading, { textAlign: "right" }]}>{row.value}</Text>
            </View>
          ))}
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <Text style={styles.muted}>
              Высота: {proposal.total_height_mm.toLocaleString("ru")} мм
            </Text>
            <Text style={styles.muted}>
              Пятно: {proposal.footprint_area_m2.toLocaleString("ru")} м²
            </Text>
          </View>
        </View>
      ) : null}

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {proposal ? (
        <View style={styles.row}>
          <Pressable style={styles.button} disabled={busy !== null} onPress={cancel}>
            <Text style={styles.buttonText}>Отмена</Text>
          </Pressable>
          <Pressable
            style={[styles.button, styles.buttonPrimary, busy !== null && { opacity: 0.5 }]}
            disabled={busy !== null}
            onPress={() => void apply()}
          >
            <Text style={styles.buttonText}>
              {busy === "apply" ? "Строим…" : "Применить и создать дом"}
            </Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.row}>
          <Pressable style={styles.button} disabled={busy !== null} onPress={onBack}>
            <Text style={styles.buttonText}>← Назад</Text>
          </Pressable>
          <Pressable
            style={[
              styles.button,
              styles.buttonPrimary,
              (!text.trim() || busy !== null) && { opacity: 0.5 },
            ]}
            disabled={!text.trim() || busy !== null}
            onPress={() => void propose()}
          >
            <Text style={styles.buttonText}>
              {busy === "propose" ? "Разбираем…" : "Показать предложение"}
            </Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}
