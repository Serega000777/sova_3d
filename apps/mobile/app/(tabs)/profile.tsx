import type { Me, PricingCatalogue } from "@physical-ai/contracts";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Alert, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { UserIcon } from "@/src/AppIcons";
import { useSession } from "@/src/session";
import { colors, elevationLow, radii, styles } from "@/src/theme";

function initials(name: string | null | undefined): string {
  const parts = name?.trim().replace(/^@/, "").split(/[\s._-]+/).filter(Boolean) ?? [];
  return parts.slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "S";
}

export default function ProfileScreen() {
  const router = useRouter();
  const { session, client, signOut } = useSession();
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [savingMode, setSavingMode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [pricing, setPricing] = useState<PricingCatalogue | null>(null);
  const name = me?.user.display_name || session?.displayName || session?.address || "Пользователь Sova";
  const currentWorkspace = me?.workspaces.find((workspace) => workspace.id === session?.workspaceId);

  useEffect(() => {
    if (!client) return;
    let cancelled = false;
    void Promise.all([client.me(), client.pricing().catch(() => null)])
      .then(([result, priceCatalogue]) => {
        if (!cancelled) {
          setMe(result);
          if (priceCatalogue) setPricing(priceCatalogue);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const marketPricing = pricing?.markets.find((market) => market.market === "ru") ?? null;
  const money = (minor: number, currency: string) => currency === "RUB"
    ? `${(minor / 100).toLocaleString("ru-RU")} ₽`
    : `$${(minor / 100).toLocaleString("en-US")}`;

  const leave = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await signOut();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  const changeExperienceMode = async (experienceMode: "beginner" | "professional") => {
    if (!client || !me || savingMode || me.user.experience_mode === experienceMode) return;
    setSavingMode(true);
    setError(null);
    try {
      const user = await client.updateMe({ experience_mode: experienceMode });
      setMe((current) => current ? { ...current, user } : current);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingMode(false);
    }
  };

  const requestDeletion = () => {
    if (!client || busy || deleting) return;
    Alert.alert(
      "Удалить аккаунт?",
      "Вход будет отключён сразу. Публичные материалы будут сняты, а связанные данные окончательно удалены не позднее чем через 30 дней. Это действие нельзя отменить в приложении.",
      [
        { text: "Отмена", style: "cancel" },
        {
          text: "Удалить аккаунт",
          style: "destructive",
          onPress: () => {
            setDeleting(true);
            setError(null);
            void client.deleteAccount()
              .then(() => signOut())
              .catch((err: unknown) => {
                setError(err instanceof Error ? err.message : String(err));
                setDeleting(false);
              });
          },
        },
      ],
    );
  };

  return (
    <SafeAreaView style={styles.screen} edges={["top"]}>
      <ScrollView contentContainerStyle={{ width: "100%", maxWidth: 640, alignSelf: "center", padding: 16, paddingBottom: 28, gap: 18 }}>
        <View style={{ gap: 5 }}>
          <Text style={[styles.title, { fontSize: 29 }]}>Профиль</Text>
          <Text style={styles.muted}>Аккаунт и текущее рабочее пространство.</Text>
        </View>

        <View style={{ borderRadius: radii.hero, padding: 20, alignItems: "center", gap: 12, backgroundColor: colors.panel, borderWidth: 1, borderColor: colors.border, ...elevationLow }}>
          <View style={{ width: 76, height: 76, borderRadius: 38, backgroundColor: colors.accentWashStrong, borderWidth: 1, borderColor: colors.accent, alignItems: "center", justifyContent: "center" }}>
            {me?.user.display_name || session?.displayName || session?.address ? (
              <Text style={{ color: colors.text, fontSize: 24, fontWeight: "800" }}>{initials(name)}</Text>
            ) : (
              <UserIcon color={colors.accent} size={34} />
            )}
          </View>
          <View style={{ alignItems: "center", gap: 4 }}>
            <Text style={[styles.title, { fontSize: 22, textAlign: "center" }]}>{name}</Text>
            {(me?.user.email || me?.user.phone || session?.address) ? <Text style={styles.muted}>{me?.user.email || me?.user.phone || session?.address}</Text> : null}
          </View>
        </View>

        <View style={{ borderRadius: radii.section, padding: 16, gap: 12, backgroundColor: colors.panel, borderWidth: 1, borderColor: colors.border }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
            <Text style={styles.heading}>Рабочее пространство</Text>
            {currentWorkspace ? <View style={styles.chip}><Text style={styles.chipText}>{currentWorkspace.role}</Text></View> : null}
          </View>
          <View style={{ backgroundColor: colors.panel2, borderRadius: radii.compact, padding: 12, gap: 4 }}>
            <Text style={styles.heading}>{currentWorkspace?.name ?? "Текущее пространство"}</Text>
            <Text style={styles.sectionSubtitle}>ID пространства</Text>
            <Text style={[styles.mono, { color: colors.muted }]} numberOfLines={1}>{session?.workspaceId ?? "—"}</Text>
          </View>
          <Text style={styles.sectionSubtitle}>Тариф: {(me?.user.plan ?? "free").toUpperCase()} · способов входа: {me?.identities.length ?? "—"}</Text>
        </View>

        {me ? (
          <View style={{ borderRadius: radii.section, padding: 16, gap: 12, backgroundColor: colors.panel, borderWidth: 1, borderColor: colors.border }}>
            <Text style={styles.heading}>Режим интерфейса</Text>
            <Text style={styles.muted}>
              Начинающий видит главные действия и подсказки. Профи видит полный набор точных CAD, mesh и проверочных инструментов. Режим не меняет тариф.
            </Text>
            <View style={{ flexDirection: "row", gap: 8 }}>
              {(["beginner", "professional"] as const).map((mode) => {
                const selected = me.user.experience_mode === mode;
                return (
                  <Pressable
                    key={mode}
                    accessibilityRole="button"
                    accessibilityState={{ selected, disabled: savingMode }}
                    disabled={savingMode}
                    onPress={() => void changeExperienceMode(mode)}
                    style={[styles.button, { flex: 1 }, selected && { borderColor: colors.accent, backgroundColor: colors.accentWashStrong }]}
                  >
                    <Text style={[styles.buttonText, selected && { color: colors.accent }]}>
                      {mode === "beginner" ? "Для начинающих" : "Для профи"}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </View>
        ) : null}

        {marketPricing ? (
          <View style={{ borderRadius: radii.section, padding: 16, gap: 12, backgroundColor: colors.panel, borderWidth: 1, borderColor: colors.border }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
              <Text style={styles.heading}>Кредиты и подписки</Text>
              <View style={styles.chip}><Text style={styles.chipText}>{pricing?.version}</Text></View>
            </View>
            <Text style={styles.muted}>Цены показаны прозрачно. Покупка и списание отключены до подключения production-биллинга.</Text>
            {marketPricing.subscriptions.map((offer) => (
              <View key={offer.code} style={{ backgroundColor: colors.panel2, borderRadius: radii.compact, padding: 12, gap: 4 }}>
                <View style={{ flexDirection: "row", justifyContent: "space-between", gap: 12 }}>
                  <Text style={styles.heading}>{offer.title_ru}</Text>
                  <Text style={{ color: colors.accent, fontWeight: "800" }}>{money(offer.monthly_price_minor, marketPricing.currency)} / мес.</Text>
                </View>
                <Text style={styles.sectionSubtitle}>{offer.included_credits.toLocaleString("ru-RU")} кредитов{offer.seats > 1 ? ` · ${offer.seats} мест` : ""}</Text>
              </View>
            ))}
            <Text style={styles.heading}>Дополнительные пакеты</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
              {marketPricing.credit_packs.map((pack) => (
                <View style={styles.chip} key={pack.code}><Text style={styles.chipText}>{pack.credits.toLocaleString("ru-RU")} · {money(pack.price_minor, marketPricing.currency)}</Text></View>
              ))}
            </View>
          </View>
        ) : null}

        <Pressable onPress={() => router.push("/printers")} style={({ pressed }) => [styles.card, { opacity: pressed ? 0.75 : 1 }]}>
          <Text style={styles.heading}>Профили принтеров</Text>
          <Text style={styles.muted}>Модель, сопло, материал и качество для точной подготовки печати.</Text>
          <Text style={{ color: colors.accent, fontWeight: "700" }}>Открыть →</Text>
        </Pressable>

        <Pressable onPress={() => router.push("/workspace-access")} style={({ pressed }) => [styles.card, { opacity: pressed ? 0.75 : 1 }]}>
          <Text style={styles.heading}>Командное пространство</Text>
          <Text style={styles.muted}>Создание и выбор workspace, проекты, участники и роли.</Text>
          <Text style={{ color: colors.accent, fontWeight: "700" }}>Открыть →</Text>
        </Pressable>

        <Pressable onPress={() => router.push("/legal")} style={({ pressed }) => [styles.card, { opacity: pressed ? 0.75 : 1 }]}>
          <Text style={styles.heading}>Конфиденциальность и условия</Text>
          <Text style={styles.muted}>Какие данные используются, как хранится контент и правила сервиса.</Text>
          <Text style={{ color: colors.accent, fontWeight: "700" }}>Открыть →</Text>
        </Pressable>

        {error && <Text style={styles.error}>{error}</Text>}

        <Pressable disabled={busy} onPress={() => void leave()} style={({ pressed }) => [styles.button, { minHeight: 48, opacity: busy ? 0.5 : pressed ? 0.75 : 1 }]}>
          <Text style={styles.buttonText}>{busy ? "Выходим…" : "Выйти из аккаунта"}</Text>
        </Pressable>

        <View style={{ borderRadius: radii.section, padding: 16, gap: 10, backgroundColor: colors.panel, borderWidth: 1, borderColor: colors.red }}>
          <Text style={styles.heading}>Удаление аккаунта</Text>
          <Text style={styles.muted}>
            Способы входа и активные сессии отключатся сразу. Проекты и связанные данные будут окончательно удалены в течение 30 дней.
          </Text>
          <Pressable
            accessibilityRole="button"
            disabled={!client || busy || deleting}
            onPress={requestDeletion}
            style={({ pressed }) => [{ minHeight: 48, borderRadius: radii.compact, borderWidth: 1, borderColor: colors.red, alignItems: "center", justifyContent: "center", opacity: deleting ? 0.5 : pressed ? 0.75 : 1 }]}
          >
            <Text style={{ color: colors.red, fontWeight: "800" }}>{deleting ? "Удаляем…" : "Удалить аккаунт"}</Text>
          </Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
