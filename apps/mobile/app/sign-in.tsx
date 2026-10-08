/**
 * Sign in (T-164, F-083): a phone or an email and the code that reaches it, or a Yandex ID /
 * VK ID account. In demo mode the code confirms itself (any address signs in) and the
 * account buttons open a demo consent step instead of the operator.
 */
import { ApiError, PhysicalAiClient, type SignInMethods } from "@physical-ai/contracts";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { probe } from "@/src/capabilities";
import { DEFAULT_BASE_URL, useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

type Channel = "phone" | "email";
type Provider = "yandex" | "vk";

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "code_rejected") {
      const left = (err.details as { attempts_left?: number } | undefined)?.attempts_left;
      return `Неверный код, осталось попыток: ${left ?? 0}`;
    }
    if (err.code === "challenge_gone") return "Код больше не действует — запросите новый";
    if (err.code === "too_many_codes") return "Слишком много кодов для этого адреса, попробуйте позже";
    if (err.code === "signin_not_enabled") return "Этот способ входа на сервере выключен";
    return err.message;
  }
  return err instanceof Error ? err.message : String(err);
}

export default function SignIn() {
  const router = useRouter();
  const { signIn } = useSession();
  const baseUrl = DEFAULT_BASE_URL;
  const client = useMemo(() => new PhysicalAiClient({ baseUrl }), [baseUrl]);
  const [methods, setMethods] = useState<SignInMethods | null>(null);
  const [channel, setChannel] = useState<Channel>("phone");
  const [address, setAddress] = useState("");
  const [challenge, setChallenge] = useState<{ id: string; address: string; devCode: string | null } | null>(null);
  const [code, setCode] = useState("");
  const [consent, setConsent] = useState<{ provider: Provider; state: string } | null>(null);
  const [consentName, setConsentName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [methodsError, setMethodsError] = useState<string | null>(null);
  const [methodsAttempt, setMethodsAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const capabilities = probe();

  useEffect(() => {
    let cancelled = false;
    setMethodsError(null);
    client
      .signInMethods()
      .then((m) => !cancelled && setMethods(m))
      .catch((err: unknown) => {
        if (cancelled) return;
        setMethodsError(describe(err));
      });
    return () => {
      cancelled = true;
    };
  }, [client, methodsAttempt]);

  async function finish(session: {
    token: string;
    workspace_id: string;
    user: { display_name: string | null; email: string | null; phone: string | null };
  }) {
    await signIn({
      baseUrl: baseUrl.trim(),
      token: session.token,
      workspaceId: session.workspace_id,
      displayName: session.user.display_name,
      address: session.user.email ?? session.user.phone ?? null,
    });
    router.replace("/");
  }

  async function requestCode() {
    if (!address.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const started = await client.requestCode({ channel, address: address.trim(), locale: "ru" });
      if (started.dev_code) {
        // demo delivery: the code confirms itself, any address signs in
        await finish(await client.verifyCode(started.challenge_id, started.dev_code));
        return;
      }
      setChallenge({ id: started.challenge_id, address: started.address, devCode: null });
      setCode("");
    } catch (err) {
      setError(describe(err));
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    const digits = code.replace(/\D/g, "");
    if (!challenge || digits.length < 6) return;
    setBusy(true);
    setError(null);
    try {
      await finish(await client.verifyCode(challenge.id, digits));
    } catch (err) {
      setError(describe(err));
      if (err instanceof ApiError && err.code === "challenge_gone") setChallenge(null);
      setBusy(false);
    }
  }

  async function startOAuth(provider: Provider) {
    setBusy(true);
    setError(null);
    try {
      // the app is its own consent page: the state comes back through the same screen
      const started = await client.oauthStart(provider, "http://app.local/sign-in", "ru");
      if (started.demo) setConsent({ provider, state: started.state });
      else setError("Вход через оператора откроется в браузере в следующей версии");
    } catch (err) {
      setError(describe(err));
    } finally {
      setBusy(false);
    }
  }

  async function finishConsent() {
    if (!consent || !consentName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await finish(await client.oauthCallback(consent.provider, `stub:${consentName.trim()}`, consent.state));
    } catch (err) {
      setError(describe(err));
      setBusy(false);
    }
  }

  const labels = methods?.labels ?? { yandex: "Yandex ID", vk: "VK ID" };

  return (
    <ScrollView style={[styles.screen, screenStyles.screen]} contentContainerStyle={[styles.content, screenStyles.content]}>
      <View style={screenStyles.authCard}>
        <View style={screenStyles.hero}>
          <View pointerEvents="none" style={screenStyles.heroArt}>
            <View style={screenStyles.heroRingOne} />
            <View style={screenStyles.heroRingTwo} />
            <View style={screenStyles.heroObject} />
          </View>
          <Text style={screenStyles.heroTitle}>Вход</Text>
          <Text style={screenStyles.heroCopy}>Опишите предмет — получите модель, которую можно править и печатать.</Text>
        </View>

        <View style={screenStyles.formBody}>

        {consent ? (
          <>
            <View style={[screenStyles.consentBrand, consent.provider === "yandex" ? screenStyles.consentYandex : screenStyles.consentVk]}>
              <View style={[screenStyles.brandMark, consent.provider === "yandex" ? screenStyles.yandexMark : screenStyles.vkMark]}>
                <Text style={screenStyles.brandMarkText}>{consent.provider === "yandex" ? "Я" : "VK"}</Text>
              </View>
              <Text style={[screenStyles.consentBrandText, consent.provider === "yandex" && screenStyles.yandexText]}>{labels[consent.provider]}</Text>
            </View>
            <Text style={styles.muted}>Демо-режим: реальный сервис не подключён. Как вас называть?</Text>
            <TextInput
              style={[styles.input, screenStyles.input]}
              value={consentName}
              onChangeText={setConsentName}
              placeholder="Ваше имя"
              placeholderTextColor={colors.muted}
              autoFocus
            />
            {error && <Text style={styles.error}>{error}</Text>}
            <View style={styles.row}>
              <Pressable
                style={[styles.button, screenStyles.primaryButton, (busy || !consentName.trim()) && screenStyles.disabled]}
                disabled={busy || !consentName.trim()}
                onPress={finishConsent}
              >
                <Text style={styles.buttonText}>{busy ? "Проверяем…" : "Продолжить"}</Text>
              </Pressable>
              <Pressable style={[styles.button, screenStyles.secondaryButton]} disabled={busy} onPress={() => setConsent(null)}>
                <Text style={styles.buttonText}>Отмена</Text>
              </Pressable>
            </View>
          </>
        ) : !methods && methodsError ? (
          <>
            <Text style={styles.error}>Не удалось связаться с сервером: {methodsError}</Text>
            <Pressable
              style={[styles.button, screenStyles.secondaryButton]}
              onPress={() => setMethodsAttempt((n) => n + 1)}
            >
              <Text style={styles.buttonText}>Повторить</Text>
            </Pressable>
          </>
        ) : !methods ? (
          <Text style={styles.muted}>Загружаем способы входа…</Text>
        ) : (
          <>
            {methods && methods.code.length > 0 && (
              <>
                <View style={screenStyles.channelTabs}>
                  {methods.code.map((c) => (
                    <Pressable
                      key={c}
                      style={[screenStyles.channelTab, channel === c && screenStyles.channelTabActive]}
                      disabled={busy || !!challenge}
                      onPress={() => setChannel(c)}
                    >
                      <Text style={[screenStyles.channelTabText, channel === c && screenStyles.channelTabTextActive]}>
                        {c === "phone" ? "Телефон" : "Почта"}
                      </Text>
                    </Pressable>
                  ))}
                </View>
                {challenge ? (
                  <>
                    <Text style={styles.muted}>Код отправлен на {challenge.address}</Text>
                    {challenge.devCode && (
                      <Text style={[styles.muted, { color: colors.yellow }]}>
                        Демо-режим: оператор не подключён, ваш код — {challenge.devCode}
                      </Text>
                    )}
                    <TextInput
                      style={[styles.input, screenStyles.input, screenStyles.codeInput]}
                      value={code}
                      onChangeText={(v) => setCode(v.replace(/[^\d ]/g, ""))}
                      keyboardType="number-pad"
                      textContentType="oneTimeCode"
                      autoComplete="one-time-code"
                      placeholder="••••••"
                      placeholderTextColor={colors.muted}
                      maxLength={7}
                      autoFocus
                    />
                    {error && <Text style={styles.error}>{error}</Text>}
                    <Pressable
                      style={[styles.button, screenStyles.primaryButton, (busy || code.replace(/\D/g, "").length < 6) && screenStyles.disabled]}
                      disabled={busy || code.replace(/\D/g, "").length < 6}
                      onPress={verify}
                    >
                      <Text style={styles.buttonText}>{busy ? "Проверяем…" : "Войти"}</Text>
                    </Pressable>
                    <View style={styles.row}>
                      <Pressable style={[styles.button, screenStyles.secondaryButton]} disabled={busy} onPress={requestCode}>
                        <Text style={styles.buttonText}>Отправить ещё раз</Text>
                      </Pressable>
                      <Pressable style={[styles.button, screenStyles.secondaryButton]} disabled={busy} onPress={() => { setChallenge(null); setError(null); }}>
                        <Text style={styles.buttonText}>Другой адрес</Text>
                      </Pressable>
                    </View>
                  </>
                ) : (
                  <>
                    <TextInput
                      style={[styles.input, screenStyles.input]}
                      value={address}
                      onChangeText={setAddress}
                      keyboardType={channel === "phone" ? "phone-pad" : "email-address"}
                      textContentType={channel === "phone" ? "telephoneNumber" : "emailAddress"}
                      autoCapitalize="none"
                      autoCorrect={false}
                      placeholder={channel === "phone" ? "+7 999 123-45-67" : "you@example.com"}
                      placeholderTextColor={colors.muted}
                    />
                    {error && <Text style={styles.error}>{error}</Text>}
                    <Pressable
                      style={[styles.button, screenStyles.primaryButton, (busy || !address.trim()) && screenStyles.disabled]}
                      disabled={busy || !address.trim()}
                      onPress={requestCode}
                    >
                      <Text style={styles.buttonText}>{busy ? "Отправляем…" : "Получить код"}</Text>
                    </Pressable>
                  </>
                )}
              </>
            )}

            {methods && methods.oauth.length > 0 && (
              <>
                <View style={screenStyles.divider}>
                  <View style={screenStyles.dividerLine} />
                  <Text style={styles.muted}>или</Text>
                  <View style={screenStyles.dividerLine} />
                </View>
                {methods.oauth.map((provider) => (
                  <Pressable
                    key={provider}
                    style={[
                      screenStyles.oauthButton,
                      provider === "yandex" ? screenStyles.yandexButton : screenStyles.vkButton,
                      busy && screenStyles.disabled,
                    ]}
                    disabled={busy}
                    onPress={() => startOAuth(provider)}
                  >
                    <View style={[screenStyles.brandMark, provider === "yandex" ? screenStyles.yandexMark : screenStyles.vkMark]}>
                      <Text style={screenStyles.brandMarkText}>{provider === "yandex" ? "Я" : "VK"}</Text>
                    </View>
                    <Text style={[screenStyles.oauthButtonText, provider === "yandex" && screenStyles.yandexText]}>{labels[provider]}</Text>
                    <Text style={[screenStyles.oauthArrow, provider === "yandex" && screenStyles.yandexText]}>→</Text>
                  </Pressable>
                ))}
              </>
            )}
          </>
        )}
        </View>
      </View>

      <View style={[styles.card, screenStyles.deviceCard]}>
        <Text style={styles.heading}>Это устройство</Text>
        <Text style={styles.muted}>
          Runtime: {capabilities.runtime} · 3D viewer: on · camera:{" "}
          {capabilities.camera ? "on" : "off"} · scanning: {capabilities.depthScan ? "on" : "off"}
        </Text>
        {capabilities.depthScanReason && (
          <Text style={styles.muted}>{capabilities.depthScanReason}</Text>
        )}
      </View>
    </ScrollView>
  );
}

const screenStyles = StyleSheet.create({
  screen: { backgroundColor: "#0d1017" },
  content: { padding: 18, paddingTop: 24, paddingBottom: 36, gap: 14 },
  authCard: {
    width: "100%",
    maxWidth: 620,
    alignSelf: "center",
    overflow: "hidden",
    borderWidth: 1,
    borderColor: "#293349",
    borderRadius: 24,
    backgroundColor: "#151922",
    shadowColor: "#000",
    shadowOpacity: 0.34,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 14 },
    elevation: 8,
  },
  hero: {
    minHeight: 196,
    justifyContent: "flex-end",
    overflow: "hidden",
    padding: 24,
    paddingRight: 92,
    backgroundColor: "#111a2a",
    borderBottomWidth: 1,
    borderBottomColor: "#25324a",
  },
  heroArt: {
    position: "absolute",
    width: 205,
    height: 205,
    right: -42,
    top: -2,
  },
  heroRingOne: {
    position: "absolute",
    width: 178,
    height: 108,
    left: 8,
    top: 43,
    borderWidth: 1,
    borderColor: "rgba(125,168,255,0.42)",
    borderRadius: 90,
    transform: [{ rotate: "-17deg" }],
  },
  heroRingTwo: {
    position: "absolute",
    width: 170,
    height: 104,
    left: 17,
    top: 47,
    borderWidth: 1,
    borderColor: "rgba(84,225,196,0.32)",
    borderRadius: 90,
    transform: [{ rotate: "29deg" }],
  },
  heroObject: {
    position: "absolute",
    width: 78,
    height: 78,
    left: 62,
    top: 58,
    borderTopLeftRadius: 23,
    borderTopRightRadius: 42,
    borderBottomRightRadius: 25,
    borderBottomLeftRadius: 38,
    backgroundColor: "#5874d9",
    borderWidth: 10,
    borderColor: "rgba(143,181,255,0.22)",
    transform: [{ rotate: "26deg" }],
    shadowColor: "#3153c6",
    shadowOpacity: 0.62,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 12 },
    elevation: 6,
  },
  heroTitle: {
    color: colors.text,
    fontSize: 34,
    lineHeight: 39,
    fontWeight: "800",
    letterSpacing: -1.2,
  },
  heroCopy: {
    maxWidth: 300,
    marginTop: 7,
    color: "#aeb9cc",
    fontSize: 14,
    lineHeight: 20,
  },
  formBody: { padding: 18, gap: 14 },
  channelTabs: {
    flexDirection: "row",
    padding: 5,
    borderWidth: 1,
    borderColor: "#314262",
    borderRadius: 999,
    backgroundColor: "#141d2b",
  },
  channelTab: {
    flex: 1,
    minHeight: 42,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 999,
  },
  channelTabActive: {
    backgroundColor: "#294f92",
    shadowColor: "#122b5e",
    shadowOpacity: 0.5,
    shadowRadius: 9,
    shadowOffset: { width: 0, height: 5 },
    elevation: 3,
  },
  channelTabText: { color: "#91a0b7", fontSize: 13, fontWeight: "700" },
  channelTabTextActive: { color: "#f5f8ff" },
  input: {
    minHeight: 52,
    paddingHorizontal: 14,
    borderColor: "#30394a",
    borderRadius: 13,
    backgroundColor: "#0e1219",
  },
  codeInput: { fontSize: 24, letterSpacing: 8, textAlign: "center" },
  primaryButton: {
    width: "100%",
    minHeight: 52,
    justifyContent: "center",
    borderColor: "#5b78df",
    borderRadius: 14,
    backgroundColor: "#426cdd",
    shadowColor: "#2146aa",
    shadowOpacity: 0.35,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 7 },
    elevation: 4,
  },
  secondaryButton: {
    flexGrow: 1,
    minHeight: 46,
    justifyContent: "center",
    borderColor: "#313a49",
    borderRadius: 13,
    backgroundColor: "#1b202a",
  },
  disabled: { opacity: 0.55 },
  divider: { flexDirection: "row", alignItems: "center", gap: 10, marginVertical: 2 },
  dividerLine: { flex: 1, height: 1, backgroundColor: "#2a3140" },
  oauthButton: {
    minHeight: 56,
    flexDirection: "row",
    alignItems: "center",
    gap: 11,
    paddingVertical: 9,
    paddingHorizontal: 10,
    borderWidth: 1,
    shadowColor: "#000",
    shadowOpacity: 0.22,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 6 },
    elevation: 3,
  },
  yandexButton: {
    borderColor: "#e7e7e5",
    borderTopLeftRadius: 18,
    borderTopRightRadius: 10,
    borderBottomRightRadius: 18,
    borderBottomLeftRadius: 18,
    backgroundColor: "#f7f7f5",
  },
  vkButton: {
    borderColor: "#258cf0",
    borderTopLeftRadius: 10,
    borderTopRightRadius: 18,
    borderBottomRightRadius: 18,
    borderBottomLeftRadius: 18,
    backgroundColor: "#0877e8",
  },
  brandMark: {
    width: 37,
    height: 37,
    alignItems: "center",
    justifyContent: "center",
  },
  yandexMark: { borderRadius: 19, backgroundColor: "#fc3f1d" },
  vkMark: { borderRadius: 12, backgroundColor: "rgba(255,255,255,0.16)" },
  brandMarkText: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: -0.3 },
  oauthButtonText: { flex: 1, color: "#fff", fontSize: 14, fontWeight: "800" },
  oauthArrow: { color: "#fff", paddingRight: 4, fontSize: 19, opacity: 0.74 },
  yandexText: { color: "#111318" },
  consentBrand: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 9,
    paddingVertical: 6,
    paddingLeft: 6,
    paddingRight: 14,
    borderWidth: 1,
    borderRadius: 999,
  },
  consentYandex: { borderColor: "#e7e7e5", backgroundColor: "#f7f7f5" },
  consentVk: { borderColor: "#258cf0", backgroundColor: "#0877e8" },
  consentBrandText: { color: "#fff", fontSize: 13, fontWeight: "800" },
  deviceCard: {
    width: "100%",
    maxWidth: 620,
    alignSelf: "center",
    marginTop: 2,
    borderRadius: 16,
    backgroundColor: "#13171f",
    opacity: 0.82,
  },
});
