/**
 * Plan-markup sheets (docs/design/MOBILE-PLAN-EDITOR.md §4-5): a text-entry sheet (a tap
 * places the anchor, this sheet gets the words — a deliberate departure from web's inline
 * floating `<input>`, which fights the OS keyboard on a phone) and the per-selected-
 * annotation action sheet (note, status, delete, photo, 3D anchor) that reuses the same
 * "selected thing -> sheet of actions" pattern this app already uses elsewhere.
 */
import type { Annotation } from "@physical-ai/contracts";
import { useEffect, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

export function PlanTextSheet({
  visible,
  language,
  onCancel,
  onSubmit,
}: {
  visible: boolean;
  language: "ru" | "en";
  onCancel: () => void;
  onSubmit: (text: string) => void;
}) {
  const ru = language === "ru";
  const [value, setValue] = useState("");
  useEffect(() => {
    if (visible) setValue("");
  }, [visible]);

  return (
    <SheetShell
      visible={visible}
      onClose={onCancel}
      maxHeightPercent="40%"
      accessibilityLabel={ru ? "Закрыть" : "Close"}
      contentGap={12}
    >
      <Text style={styles.title}>{ru ? "Текст на плане" : "Text on the plan"}</Text>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={setValue}
        placeholder={ru ? "Текст…" : "Text…"}
        placeholderTextColor={colors.muted}
        autoFocus
        multiline
      />
      <View style={styles.row}>
        <Pressable style={styles.button} onPress={onCancel}>
          <Text style={styles.buttonText}>{ru ? "Отмена" : "Cancel"}</Text>
        </Pressable>
        <Pressable
          style={[styles.button, styles.buttonPrimary, { flexGrow: 1 }, !value.trim() && { opacity: 0.5 }]}
          disabled={!value.trim()}
          onPress={() => onSubmit(value)}
        >
          <Text style={styles.buttonText}>{ru ? "Поставить" : "Place"}</Text>
        </Pressable>
      </View>
    </SheetShell>
  );
}

export function PlanAnnotationSheet({
  visible,
  annotation,
  language,
  onClose,
  onNoteChange,
  onToggleStatus,
  onDelete,
  onAttachPhoto,
  attachmentBusy,
  photoCount,
  onPlaceIn3D,
  onShowIn3D,
  onRemoveAnchor,
}: {
  visible: boolean;
  annotation: Annotation | null;
  language: "ru" | "en";
  onClose: () => void;
  onNoteChange: (note: string) => void;
  onToggleStatus: () => void;
  onDelete: () => void;
  onAttachPhoto: () => void;
  attachmentBusy: boolean;
  photoCount: number;
  onPlaceIn3D: () => void;
  onShowIn3D: () => void;
  onRemoveAnchor: () => void;
}) {
  const ru = language === "ru";
  if (!annotation) return null;
  const hasAnchor = Boolean(annotation.model_anchor_mm);

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="70%"
      accessibilityLabel={ru ? "Закрыть" : "Close"}
      contentGap={12}
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <Text style={styles.title}>{ru ? "Замечание" : "Remark"}</Text>
        <Pressable onPress={onClose} hitSlop={12} accessibilityLabel={ru ? "Закрыть" : "Close"}>
          <Text style={[styles.title, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>
      <TextInput
        style={[styles.input, { minHeight: 70 }]}
        value={annotation.note}
        onChangeText={onNoteChange}
        placeholder={ru ? "Комментарий…" : "Comment…"}
        placeholderTextColor={colors.muted}
        multiline
      />
      {photoCount > 0 && <Text style={styles.muted}>{ru ? `Фото: ${photoCount}` : `Photos: ${photoCount}`}</Text>}
      <View style={styles.row}>
        <Pressable style={[styles.button, attachmentBusy && { opacity: 0.6 }]} disabled={attachmentBusy} onPress={onAttachPhoto}>
          <Text style={styles.buttonText}>{attachmentBusy ? (ru ? "Загрузка…" : "Uploading…") : ru ? "+ Фото" : "+ Photo"}</Text>
        </Pressable>
        <Pressable style={styles.button} onPress={onToggleStatus}>
          <Text style={styles.buttonText}>
            {annotation.status === "open" ? (ru ? "Решено" : "Resolved") : ru ? "Открыть снова" : "Reopen"}
          </Text>
        </Pressable>
      </View>
      <View style={styles.row}>
        {hasAnchor ? (
          <>
            <Pressable style={styles.button} onPress={onShowIn3D}>
              <Text style={styles.buttonText}>{ru ? "Показать в 3D" : "Show in 3D"}</Text>
            </Pressable>
            <Pressable style={styles.button} onPress={onRemoveAnchor}>
              <Text style={styles.buttonText}>{ru ? "Убрать 3D-точку" : "Remove 3D point"}</Text>
            </Pressable>
          </>
        ) : (
          <Pressable style={styles.button} onPress={onPlaceIn3D}>
            <Text style={styles.buttonText}>{ru ? "Указать в 3D" : "Place in 3D"}</Text>
          </Pressable>
        )}
      </View>
      <Pressable style={[styles.button, { borderColor: colors.red }]} onPress={onDelete}>
        <Text style={[styles.buttonText, { color: colors.red }]}>{ru ? "Удалить" : "Delete"}</Text>
      </Pressable>
    </SheetShell>
  );
}
