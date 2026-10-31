import type { AnimationCommandProposal } from "@physical-ai/contracts";
import { Pressable, Text, TextInput, View } from "react-native";

import { styles } from "./theme";

export function AnimationCommandCard({
  language,
  prompt,
  proposal,
  disabled,
  onPromptChange,
  onPropose,
  onApply,
}: {
  language: "ru" | "en";
  prompt: string;
  proposal: AnimationCommandProposal | null;
  disabled: boolean;
  onPromptChange: (value: string) => void;
  onPropose: () => void;
  onApply: () => void;
}) {
  const ru = language === "ru";
  return (
    <View style={[styles.card, { gap: 10 }]} accessibilityLabel={ru ? "Команда анимации" : "Animation command"}>
      <Text style={styles.heading}>{ru ? "Команда анимации" : "Animation command"}</Text>
      <Text style={styles.muted}>{ru
        ? "Введите «открой за 2 секунды» или «закрой за 2 секунды». Сначала проверьте предложение."
        : "Enter “open in 2 seconds” or “close in 2 seconds”. Review the proposal first."}</Text>
      <TextInput
        style={styles.input}
        value={prompt}
        editable={!disabled}
        onChangeText={onPromptChange}
        placeholder={ru ? "Например: закрой за 2 секунды" : "For example: close in 2 seconds"}
        placeholderTextColor="#7f8794"
      />
      <Pressable
        accessibilityRole="button"
        style={[styles.button, (disabled || !prompt.trim()) && { opacity: 0.5 }]}
        disabled={disabled || !prompt.trim()}
        onPress={onPropose}
      >
        <Text style={styles.buttonText}>{ru ? "Подготовить предложение" : "Prepare proposal"}</Text>
      </Pressable>
      {proposal ? (
        <View style={{ gap: 8 }}>
          <Text style={styles.text}>{ru
            ? `${proposal.clip.direction === "reverse" ? "Закрытие" : "Открытие"}: ${proposal.clip.duration_seconds} с · ${proposal.clip.joint_type}`
            : `${proposal.clip.direction === "reverse" ? "Close" : "Open"}: ${proposal.clip.duration_seconds}s · ${proposal.clip.joint_type}`}</Text>
          <Text style={styles.muted}>{ru
            ? "Предложение только для чтения: фоновая задача и модель не запускались. Применение создаст новую неизменяемую версию."
            : "This proposal is read-only: no background job or model was run. Applying it creates a new immutable version."}</Text>
          <Pressable
            accessibilityRole="button"
            style={[styles.button, styles.buttonPrimary, disabled && { opacity: 0.5 }]}
            disabled={disabled}
            onPress={onApply}
          >
            <Text style={styles.buttonText}>{ru ? "Применить к новой версии" : "Apply to new version"}</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}
