import type { PhysicalAiClient, ShareLinkOut } from "@physical-ai/contracts";
import Constants from "expo-constants";
import { useCallback, useEffect, useState } from "react";
import { Alert, Pressable, Share, Text, View } from "react-native";

import { projectShareLinkState, projectSharePageUrl } from "./project-share-links";
import { colors, styles } from "./theme";

const EXPIRY_OPTIONS = [
  { hours: 24, label: "1 день" },
  { hours: 24 * 7, label: "7 дней" },
  { hours: 24 * 30, label: "30 дней" },
] as const;

export function ProjectShareLinksCard({
  client,
  projectId,
  apiBaseUrl,
  hasVersion,
}: {
  client: PhysicalAiClient;
  projectId: string;
  apiBaseUrl: string;
  hasVersion: boolean;
}) {
  const [links, setLinks] = useState<ShareLinkOut[]>([]);
  const [expiresInHours, setExpiresInHours] = useState(24 * 7);
  const [created, setCreated] = useState<{ id: string; url: string } | null>(null);
  const [busy, setBusy] = useState<"load" | "create" | "revoke" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy("load");
    setError(null);
    try {
      setLinks(await client.listProjectShareLinks(projectId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }, [client, projectId]);

  useEffect(() => {
    setCreated(null);
    void load();
  }, [load]);

  async function createLink() {
    if (!hasVersion || busy) return;
    setBusy("create");
    setError(null);
    try {
      const result = await client.createProjectShareLink(projectId, {
        expires_in_hours: expiresInHours,
      });
      const url = projectSharePageUrl({
        token: result.token,
        apiBaseUrl,
        webBaseUrl:
          process.env.EXPO_PUBLIC_WEB_URL
          ?? (Constants.expoConfig?.extra?.webUrl as string | undefined),
      });
      setCreated({ id: result.id, url });
      setLinks(await client.listProjectShareLinks(projectId));
      await Share.share({
        title: "Sova 3D — просмотр проекта",
        message: `Проект Sova 3D доступен только для просмотра до ${new Date(result.expires_at).toLocaleString("ru-RU")}\n${url}`,
        url,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  function confirmRevoke(linkId: string) {
    if (busy) return;
    Alert.alert(
      "Отозвать ссылку?",
      "Она сразу перестанет открывать проект. Это действие не удаляет сам проект.",
      [
        { text: "Отмена", style: "cancel" },
        {
          text: "Отозвать",
          style: "destructive",
          onPress: () => void revokeLink(linkId),
        },
      ],
    );
  }

  async function revokeLink(linkId: string) {
    if (busy) return;
    setBusy("revoke");
    setError(null);
    try {
      await client.revokeProjectShareLink(projectId, linkId);
      if (created?.id === linkId) setCreated(null);
      setLinks(await client.listProjectShareLinks(projectId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function shareCreated() {
    if (!created) return;
    await Share.share({
      title: "Sova 3D — просмотр проекта",
      message: created.url,
      url: created.url,
    });
  }

  return (
    <View style={[styles.card, { gap: 12 }]} accessibilityLabel="Ссылки на просмотр проекта">
      <View style={{ gap: 4 }}>
        <Text style={styles.heading}>Поделиться проектом</Text>
        <Text style={styles.muted}>
          Временная ссылка открывает только текущую версию без аккаунта и без прав на изменение.
          Секрет показывается один раз и не хранится на сервере в открытом виде.
        </Text>
      </View>

      <View style={styles.row} accessibilityRole="radiogroup">
        {EXPIRY_OPTIONS.map((option) => (
          <Pressable
            key={option.hours}
            accessibilityRole="radio"
            accessibilityState={{ checked: expiresInHours === option.hours }}
            disabled={Boolean(busy)}
            onPress={() => setExpiresInHours(option.hours)}
            style={[
              styles.chip,
              expiresInHours === option.hours && {
                borderColor: colors.accent,
                backgroundColor: colors.accentWashStrong,
              },
            ]}
          >
            <Text style={styles.chipText}>{option.label}</Text>
          </Pressable>
        ))}
      </View>
      <Pressable
        accessibilityRole="button"
        disabled={!hasVersion || Boolean(busy)}
        onPress={() => void createLink()}
        style={[styles.button, styles.buttonPrimary, (!hasVersion || busy) && { opacity: 0.5 }]}
      >
        <Text style={styles.buttonText}>{busy === "create" ? "Создаём…" : "Создать и поделиться"}</Text>
      </Pressable>
      {!hasVersion ? (
        <Text style={[styles.sectionSubtitle, { color: colors.yellow }]}>Сначала сохраните хотя бы одну версию проекта.</Text>
      ) : null}

      {created ? (
        <View style={{ gap: 8, padding: 10, borderRadius: 10, backgroundColor: colors.panel2 }}>
          <Text style={styles.sectionSubtitle}>Скопируйте сейчас — повторно показать этот адрес нельзя:</Text>
          <Text selectable style={styles.mono}>{created.url}</Text>
          <Pressable accessibilityRole="button" onPress={() => void shareCreated()} style={styles.button}>
            <Text style={styles.buttonText}>Поделиться ещё раз</Text>
          </Pressable>
        </View>
      ) : null}

      {error ? <Text style={[styles.sectionSubtitle, { color: colors.red }]}>{error}</Text> : null}
      {busy === "load" ? <Text style={styles.sectionSubtitle}>Загружаем ссылки…</Text> : null}
      {links.map((link) => {
        const state = projectShareLinkState(link);
        const status = state === "active" ? "активна" : state === "expired" ? "истекла" : "отозвана";
        const statusColor = state === "active" ? colors.green : state === "expired" ? colors.yellow : colors.red;
        return (
          <View key={link.id} style={{ gap: 7, paddingTop: 9, borderTopColor: colors.border, borderTopWidth: 1 }}>
            <View style={[styles.row, { justifyContent: "space-between" }]}>
              <Text style={[styles.sectionSubtitle, { color: statusColor }]}>{status}</Text>
              <Text style={styles.sectionSubtitle}>до {new Date(link.expires_at).toLocaleString("ru-RU")}</Text>
            </View>
            <Text style={styles.sectionSubtitle}>
              Создана {new Date(link.created_at).toLocaleString("ru-RU")}
              {link.last_used_at ? ` · открыта ${new Date(link.last_used_at).toLocaleString("ru-RU")}` : " · ещё не открывалась"}
            </Text>
            {state === "active" ? (
              <Pressable accessibilityRole="button" disabled={Boolean(busy)} onPress={() => confirmRevoke(link.id)} style={styles.button}>
                <Text style={styles.buttonText}>Отозвать</Text>
              </Pressable>
            ) : null}
          </View>
        );
      })}
    </View>
  );
}
