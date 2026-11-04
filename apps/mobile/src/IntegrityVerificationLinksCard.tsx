import type { PhysicalAiClient, VerificationLinkOut } from "@physical-ai/contracts";
import Constants from "expo-constants";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Pressable, Share, Text, View } from "react-native";

import { colors, styles } from "./theme";
import {
  verificationLinkPageUrl,
  verificationLinkState,
} from "./verification-links";

const EXPIRY_OPTIONS = [
  { hours: 24, ru: "1 день", en: "1 day" },
  { hours: 24 * 7, ru: "7 дней", en: "7 days" },
  { hours: 24 * 30, ru: "30 дней", en: "30 days" },
] as const;

export function IntegrityVerificationLinksCard({
  client,
  versionId,
  apiBaseUrl,
  language,
}: {
  client: PhysicalAiClient;
  versionId: string;
  apiBaseUrl: string;
  language: "ru" | "en";
}) {
  const ru = language === "ru";
  const [links, setLinks] = useState<VerificationLinkOut[]>([]);
  const [expiresInHours, setExpiresInHours] = useState(24 * 7);
  const [created, setCreated] = useState<{ id: string; url: string } | null>(null);
  const [busy, setBusy] = useState<"load" | "create" | "revoke" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const versionIdRef = useRef(versionId);
  versionIdRef.current = versionId;

  const load = useCallback(async () => {
    const sourceVersionId = versionId;
    setBusy("load");
    setError(null);
    try {
      const next = await client.listVerificationLinks(sourceVersionId);
      if (versionIdRef.current === sourceVersionId) setLinks(next);
    } catch (reason) {
      if (versionIdRef.current === sourceVersionId) {
        setLinks([]);
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (versionIdRef.current === sourceVersionId) setBusy(null);
    }
  }, [client, versionId]);

  useEffect(() => {
    setCreated(null);
    void load();
  }, [load]);

  async function createLink() {
    if (busy) return;
    const sourceVersionId = versionId;
    setBusy("create");
    setError(null);
    try {
      const result = await client.createVerificationLink(sourceVersionId, {
        expires_in_hours: expiresInHours,
      });
      const url = verificationLinkPageUrl({
        token: result.token,
        apiBaseUrl,
        webBaseUrl:
          process.env.EXPO_PUBLIC_WEB_URL
          ?? (Constants.expoConfig?.extra?.webUrl as string | undefined),
      });
      if (versionIdRef.current === sourceVersionId) {
        setCreated({ id: result.id, url });
      }
      await Share.share({
        title: ru ? "Sova 3D — проверка отчёта" : "Sova 3D — report verification",
        message: ru
          ? `Публичная проверка отчёта доступна до ${new Date(result.expires_at).toLocaleString("ru-RU")}\n${url}`
          : `The public report verification is available until ${new Date(result.expires_at).toLocaleString("en-US")}\n${url}`,
        url,
      });
      if (versionIdRef.current === sourceVersionId) {
        const next = await client.listVerificationLinks(sourceVersionId);
        if (versionIdRef.current === sourceVersionId) setLinks(next);
      }
    } catch (reason) {
      if (versionIdRef.current === sourceVersionId) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (versionIdRef.current === sourceVersionId) setBusy(null);
    }
  }

  function confirmRevoke(linkId: string) {
    if (busy) return;
    Alert.alert(
      ru ? "Отозвать ссылку?" : "Revoke link?",
      ru
        ? "Публичная страница сразу перестанет открываться. Отчёт и версия модели не изменятся."
        : "The public page will stop opening immediately. The report and model version stay unchanged.",
      [
        { text: ru ? "Отмена" : "Cancel", style: "cancel" },
        {
          text: ru ? "Отозвать" : "Revoke",
          style: "destructive",
          onPress: () => void revoke(linkId),
        },
      ],
    );
  }

  async function revoke(linkId: string) {
    const sourceVersionId = versionId;
    setBusy("revoke");
    setError(null);
    try {
      await client.revokeVerificationLink(sourceVersionId, linkId);
      const next = await client.listVerificationLinks(sourceVersionId);
      if (versionIdRef.current === sourceVersionId) {
        if (created?.id === linkId) setCreated(null);
        setLinks(next);
      }
    } catch (reason) {
      if (versionIdRef.current === sourceVersionId) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (versionIdRef.current === sourceVersionId) setBusy(null);
    }
  }

  return (
    <View
      style={[styles.card, { gap: 10, borderColor: colors.accent }]}
      accessibilityLabel={ru ? "Публичные ссылки проверки отчёта" : "Public report verification links"}
    >
      <View style={{ gap: 3 }}>
        <Text style={styles.heading}>{ru ? "Публичная проверка отчёта" : "Public report verification"}</Text>
        <Text style={styles.muted}>
          {ru
            ? "Owner-only ссылка открывает без аккаунта только сохранённый integrity report этой immutable-версии. Она отзывается и не является цифровой подписью или сертификатом."
            : "This owner-only link opens only this immutable version's persisted integrity report without an account. It is revocable and is not a digital signature or certificate."}
        </Text>
      </View>

      <View style={[styles.row, { flexWrap: "wrap" }]}>
        {EXPIRY_OPTIONS.map((option) => (
          <Pressable
            key={option.hours}
            accessibilityRole="radio"
            accessibilityState={{ checked: expiresInHours === option.hours }}
            style={[styles.chip, expiresInHours === option.hours && { borderColor: colors.accent }]}
            disabled={busy !== null}
            onPress={() => setExpiresInHours(option.hours)}
          >
            <Text style={[styles.chipText, expiresInHours === option.hours && { color: colors.accent }]}>
              {ru ? option.ru : option.en}
            </Text>
          </Pressable>
        ))}
      </View>
      <Pressable
        accessibilityRole="button"
        style={[styles.button, styles.buttonPrimary, busy !== null && { opacity: 0.45 }]}
        disabled={busy !== null}
        onPress={() => void createLink()}
      >
        <Text style={styles.buttonText}>
          {busy === "create" ? (ru ? "Создаём…" : "Creating…") : (ru ? "Создать и поделиться" : "Create and share")}
        </Text>
      </Pressable>

      {created ? (
        <View style={{ gap: 5 }}>
          <Text style={styles.sectionSubtitle}>
            {ru ? "Секрет показывается только сейчас и не сохраняется в приложении." : "The secret is shown only now and is not persisted by the app."}
          </Text>
          <Text selectable style={styles.mono}>{created.url}</Text>
          <Pressable style={styles.button} disabled={busy !== null} onPress={() => void Share.share({ message: created.url, url: created.url })}>
            <Text style={styles.buttonText}>{ru ? "Поделиться ещё раз" : "Share again"}</Text>
          </Pressable>
        </View>
      ) : null}

      {busy === "load" ? <Text style={styles.muted}>{ru ? "Загружаем ссылки…" : "Loading links…"}</Text> : null}
      {links.map((link) => {
        const state = verificationLinkState(link);
        return (
          <View key={link.id} style={[styles.row, { justifyContent: "space-between", alignItems: "center" }]}>
            <Text style={[styles.muted, { flex: 1 }]}>
              {new Date(link.created_at).toLocaleDateString(ru ? "ru-RU" : "en-US")} · {ru ? "до" : "until"} {new Date(link.expires_at).toLocaleDateString(ru ? "ru-RU" : "en-US")} · {
                state === "active" ? (ru ? "активна" : "active") : state === "revoked" ? (ru ? "отозвана" : "revoked") : (ru ? "истекла" : "expired")
              }
            </Text>
            {state === "active" ? (
              <Pressable style={styles.button} disabled={busy !== null} onPress={() => confirmRevoke(link.id)}>
                <Text style={styles.buttonText}>{ru ? "Отозвать" : "Revoke"}</Text>
              </Pressable>
            ) : null}
          </View>
        );
      })}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}
