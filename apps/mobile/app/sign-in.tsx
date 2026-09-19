/**
 * Sign in (T-164, F-083): a phone or an email and the code that reaches it, or a Yandex ID /
 * VK ID account. In demo mode the code confirms itself (any address signs in) and the
 * account buttons open a demo consent step instead of the operator.
 */
import { ApiError, PhysicalAiClient, type SignInMethods } from "@physical-ai/contracts";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { probe } from "@/src/capabilities";
import { DEFAULT_BASE_URL, useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

type Channel = "phone" | "email";
type Provider = "yandex" | "vk";

const BRAND: Record<Provider, string> = { yandex: "#fc3f1d", vk: "#0077ff" };

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
  const [busy, setBusy] = useState(false);
  const capabilities = probe();

  useEffect(() => {
    let cancelled = false;
    client
      .signInMethods()
      .then((m) => !cancelled && setMethods(m))
      .catch((err: unknown) => !cancelled && setError(describe(err)));
    return () => {
      cancelled = true;
    };
  }, [client]);

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
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.card}>
        <Text style={styles.heading}>Вход</Text>
        <Text style={styles.muted}>Опишите предмет — получите модель, которую можно править и печатать.</Text>

        {consent ? (
          <>
            <View style={[styles.chip, { backgroundColor: BRAND[consent.provider], borderColor: BRAND[consent.provider], alignSelf: "flex-start" }]}>
              <Text style={[styles.chipText, { color: "#fff", fontWeight: "700" }]}>{labels[consent.provider]}</Text>
            </View>
            <Text style={styles.muted}>Демо-режим: реальный сервис не подключён. Как вас называть?</Text>
            <TextInput
              style={styles.input}
              value={consentName}
              onChangeText={setConsentName}
              placeholder="Ваше имя"
              placeholderTextColor={colors.muted}
              autoFocus
            />
            {error && <Text style={styles.error}>{error}</Text>}
            <View style={styles.row}>
              <Pressable
                style={[styles.button, styles.buttonPrimary, (busy || !consentName.trim()) && { opacity: 0.6 }]}
                disabled={busy || !consentName.trim()}
                onPress={finishConsent}
              >
                <Text style={styles.buttonText}>{busy ? "Проверяем…" : "Продолжить"}</Text>
              </Pressable>
              <Pressable style={styles.button} disabled={busy} onPress={() => setConsent(null)}>
                <Text style={styles.buttonText}>Отмена</Text>
              </Pressable>
            </View>
          </>
        ) : (
          <>
            {methods && methods.code.length > 0 && (
              <>
                <View style={styles.row}>
                  {methods.code.map((c) => (
                    <Pressable
                      key={c}
                      style={[styles.chip, channel === c && { borderColor: colors.accent }]}
                      disabled={busy || !!challenge}
                      onPress={() => setChannel(c)}
                    >
                      <Text style={[styles.chipText, channel === c && { color: colors.accent }]}>
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
                      style={[styles.input, { fontSize: 24, letterSpacing: 8, textAlign: "center" }]}
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
                      style={[styles.button, styles.buttonPrimary, (busy || code.replace(/\D/g, "").length < 6) && { opacity: 0.6 }]}
                      disabled={busy || code.replace(/\D/g, "").length < 6}
                      onPress={verify}
                    >
                      <Text style={styles.buttonText}>{busy ? "Проверяем…" : "Войти"}</Text>
                    </Pressable>
                    <View style={styles.row}>
                      <Pressable style={styles.button} disabled={busy} onPress={requestCode}>
                        <Text style={styles.buttonText}>Отправить ещё раз</Text>
                      </Pressable>
                      <Pressable style={styles.button} disabled={busy} onPress={() => { setChallenge(null); setError(null); }}>
                        <Text style={styles.buttonText}>Другой адрес</Text>
                      </Pressable>
                    </View>
                  </>
                ) : (
                  <>
                    <TextInput
                      style={styles.input}
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
                      style={[styles.button, styles.buttonPrimary, (busy || !address.trim()) && { opacity: 0.6 }]}
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
                <Text style={[styles.muted, { textAlign: "center" }]}>или</Text>
                {methods.oauth.map((provider) => (
                  <Pressable
                    key={provider}
                    style={[styles.button, { backgroundColor: BRAND[provider], borderColor: BRAND[provider] }, busy && { opacity: 0.6 }]}
                    disabled={busy}
                    onPress={() => startOAuth(provider)}
                  >
                    <Text style={[styles.buttonText, { color: "#fff", fontWeight: "700" }]}>{labels[provider]}</Text>
                  </Pressable>
                ))}
              </>
            )}
          </>
        )}
      </View>

      <View style={styles.card}>
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
