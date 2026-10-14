/**
 * Premium mobile authentication for Sova 3D. The server uses passwordless sign-in:
 * a phone/email receives a one-time code, while supported identity providers keep
 * their existing API flow. "Create" and "sign in" intentionally share that secure
 * backend path and differ only in the first-run copy.
 */
import { ApiError, PhysicalAiClient, type SignInMethods } from "@physical-ai/contracts";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Animated,
  Easing,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { Onboarding } from "@/src/Onboarding";
import { VkIdIcon, YandexIdIcon } from "@/src/ProviderIcons";
import { DEFAULT_BASE_URL, useSession } from "@/src/session";
import { colors } from "@/src/theme";

type Channel = "phone" | "email";
type Provider = "yandex" | "vk";
type AuthView = "welcome" | "signup" | "signin";

const METHODS_TIMEOUT_MS = 8_000;
const HERO = require("../assets/auth/sova-villa-night.png") as number;

async function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_, reject) => {
        timer = setTimeout(() => reject(new Error("сервер не ответил за 8 секунд")), timeoutMs);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

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
  if (
    err instanceof Error &&
    /(fetch failed|network request failed|could not connect|server.*not respond|timed? out)/i.test(err.message)
  ) {
    return "Сервер временно недоступен. Проверьте подключение и попробуйте ещё раз.";
  }
  return err instanceof Error ? err.message : String(err);
}

export default function SignIn() {
  const router = useRouter();
  const { signIn } = useSession();
  const baseUrl = DEFAULT_BASE_URL;
  const client = useMemo(() => new PhysicalAiClient({ baseUrl }), [baseUrl]);
  const [view, setView] = useState<AuthView>("welcome");
  const [methods, setMethods] = useState<SignInMethods | null>(null);
  const [channel, setChannel] = useState<Channel>("email");
  const [address, setAddress] = useState("");
  const [challenge, setChallenge] = useState<{ id: string; address: string } | null>(null);
  const [code, setCode] = useState("");
  const [consent, setConsent] = useState<{ provider: Provider; state: string } | null>(null);
  const [consentName, setConsentName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [methodsError, setMethodsError] = useState<string | null>(null);
  const [methodsAttempt, setMethodsAttempt] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setMethodsError(null);
    withTimeout(client.signInMethods(), METHODS_TIMEOUT_MS)
      .then((nextMethods) => {
        if (cancelled) return;
        setMethods(nextMethods);
        if (!nextMethods.code.includes(channel) && nextMethods.code[0]) {
          setChannel(nextMethods.code[0]);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setMethodsError(describe(err));
      });
    return () => {
      cancelled = true;
    };
  }, [channel, client, methodsAttempt]);

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

  function showForm(next: Exclude<AuthView, "welcome">) {
    setView(next);
    setChallenge(null);
    setCode("");
    setError(null);
    setConsent(null);
  }

  async function requestCode() {
    if (!address.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const started = await client.requestCode({ channel, address: address.trim(), locale: "ru" });
      if (started.dev_code) {
        await finish(await client.verifyCode(started.challenge_id, started.dev_code));
        return;
      }
      setChallenge({ id: started.challenge_id, address: started.address });
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

  if (view === "welcome" && !consent) {
    return (
      <>
        <SafeAreaView style={screen.safeArea} edges={["top", "bottom"]}>
          <View style={screen.welcome}>
            <Image source={HERO} style={screen.heroImage} resizeMode="cover" />
            <View pointerEvents="none" style={screen.heroShade} />

            <View style={screen.welcomeTop}>
              <View style={screen.brandRow}>
                <View style={screen.brandMark}><Text style={screen.brandMarkText}>S</Text></View>
                <Text style={screen.brandName}>Sova <Text style={screen.brandAccent}>3D</Text></Text>
              </View>
              <Text style={screen.welcomeTitle}>Добро пожаловать{`\n`}в Sova 3D!</Text>
              <Text style={screen.welcomeCopy}>
                Создавайте дома, интерьеры, экстерьеры и целые миры вместе с нами.
              </Text>
            </View>

            <View style={screen.welcomeActions}>
              <Pressable style={screen.primaryButton} onPress={() => showForm("signup")}>
                <Text style={screen.primaryButtonText}>Создать аккаунт</Text>
              </Pressable>
              <Pressable style={screen.outlineButton} onPress={() => showForm("signin")}>
                <Text style={screen.outlineButtonText}>Войти</Text>
              </Pressable>
              <ProviderBlock
                methods={methods}
                labels={labels}
                busy={busy}
                onPress={startOAuth}
                compact
              />
              {methodsError && (
                <Pressable style={screen.connectionHint} onPress={() => setMethodsAttempt((value) => value + 1)}>
                  <Text style={screen.connectionHintText}>Сервер недоступен · Повторить</Text>
                </Pressable>
              )}
              <Text style={screen.terms}>
                Продолжая, вы соглашаетесь с{`\n`}
                <Text style={screen.termsLink}>Условиями использования</Text> и{` `}
                <Text style={screen.termsLink}>Политикой конфиденциальности</Text>
              </Text>
            </View>
          </View>
        </SafeAreaView>
        <Onboarding
          language="ru"
          onComplete={() => showForm("signup")}
          onSignIn={() => showForm("signin")}
        />
      </>
    );
  }

  const isSignup = view === "signup";

  return (
    <>
      <SafeAreaView style={screen.safeArea} edges={["top", "bottom"]}>
        <KeyboardAvoidingView
          style={screen.flex}
          behavior={Platform.OS === "ios" ? "padding" : undefined}
        >
          <ScrollView
            style={screen.formScroll}
            contentContainerStyle={screen.formContent}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Назад"
            hitSlop={14}
            style={screen.backButton}
            onPress={() => {
              if (consent) setConsent(null);
              else if (challenge) setChallenge(null);
              else setView("welcome");
              setError(null);
            }}
          >
            <Text style={screen.backIcon}>‹</Text>
          </Pressable>

          <View style={screen.formHeader}>
            <Text style={screen.formEyebrow}>{isSignup ? "SOVA ID  /  NEW USER" : "SOVA ID  /  RETURN"}</Text>
            <Text style={screen.formTitle}>
              {consent
                ? `Вход через ${labels[consent.provider]}`
                : challenge
                  ? "Введите код"
                  : isSignup
                    ? "Создание аккаунта"
                    : "Вход в аккаунт"}
            </Text>
            <Text style={screen.formSubtitle}>
              {consent
                ? "Подтвердите имя для демо-профиля"
                : challenge
                  ? `Мы отправили одноразовый код на ${challenge.address}`
                  : isSignup
                    ? "Начните создавать свои 3D-проекты уже сегодня"
                    : "С возвращением! Продолжайте создавать удивительные проекты."}
            </Text>
            {!consent && !challenge && <TechSignal />}
          </View>

          {consent ? (
            <View style={screen.formStack}>
              <View style={screen.inputShell}>
                <Text style={screen.inputIcon}>◯</Text>
                <TextInput
                  style={screen.input}
                  value={consentName}
                  onChangeText={setConsentName}
                  placeholder="Ваше имя"
                  placeholderTextColor={colors.muted}
                  autoFocus
                />
              </View>
              {error && <ErrorMessage text={error} />}
              <Pressable
                style={[screen.primaryButton, (busy || !consentName.trim()) && screen.disabled]}
                disabled={busy || !consentName.trim()}
                onPress={finishConsent}
              >
                <Text style={screen.primaryButtonText}>{busy ? "Проверяем…" : "Продолжить"}</Text>
              </Pressable>
            </View>
          ) : methodsError && !methods ? (
            <View style={screen.formStack}>
              <ErrorMessage text={`Не удалось связаться с сервером: ${methodsError}`} />
              <Pressable style={screen.outlineButton} onPress={() => setMethodsAttempt((value) => value + 1)}>
                <Text style={screen.outlineButtonText}>Повторить</Text>
              </Pressable>
            </View>
          ) : !methods ? (
            <View style={screen.loadingCard}><Text style={screen.loadingText}>Подключаем безопасный вход…</Text></View>
          ) : methods.code.length === 0 && methods.oauth.length === 0 ? (
            <View style={screen.formStack}>
              <ErrorMessage text="Сервер пока не включил ни одного способа входа." />
              <Pressable style={screen.outlineButton} onPress={() => setMethodsAttempt((value) => value + 1)}>
                <Text style={screen.outlineButtonText}>Проверить снова</Text>
              </Pressable>
            </View>
          ) : challenge ? (
            <View style={screen.formStack}>
              <View style={[screen.inputShell, screen.codeShell]}>
                <TextInput
                  style={[screen.input, screen.codeInput]}
                  value={code}
                  onChangeText={(value) => setCode(value.replace(/[^\d ]/g, ""))}
                  keyboardType="number-pad"
                  textContentType="oneTimeCode"
                  autoComplete="one-time-code"
                  placeholder="••••••"
                  placeholderTextColor="#55585d"
                  maxLength={7}
                  autoFocus
                />
              </View>
              {error && <ErrorMessage text={error} />}
              <Pressable
                style={[screen.primaryButton, (busy || code.replace(/\D/g, "").length < 6) && screen.disabled]}
                disabled={busy || code.replace(/\D/g, "").length < 6}
                onPress={verify}
              >
                <Text style={screen.primaryButtonText}>{busy ? "Проверяем…" : "Продолжить"}</Text>
              </Pressable>
              <Pressable disabled={busy} onPress={requestCode}>
                <Text style={screen.inlineLink}>Отправить код ещё раз</Text>
              </Pressable>
            </View>
          ) : (
            <View style={screen.formStack}>
              {methods.code.length > 1 && (
                <View style={screen.channelTabs}>
                  {methods.code.map((item) => (
                    <Pressable
                      key={item}
                      style={[screen.channelTab, channel === item && screen.channelTabActive]}
                      disabled={busy}
                      onPress={() => setChannel(item)}
                    >
                      <Text style={[screen.channelText, channel === item && screen.channelTextActive]}>
                        {item === "email" ? "Email" : "Телефон"}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              )}

              <View style={screen.addressField}>
                <Text style={screen.inputLabel}>{channel === "phone" ? "PHONE / MOBILE" : "EMAIL / ADDRESS"}</Text>
                <View style={screen.inputRail}>
                  <TextInput
                    style={screen.addressInput}
                    value={address}
                    onChangeText={setAddress}
                    keyboardType={channel === "phone" ? "phone-pad" : "email-address"}
                    textContentType={channel === "phone" ? "telephoneNumber" : "emailAddress"}
                    autoCapitalize="none"
                    autoCorrect={false}
                    placeholder={channel === "phone" ? "+7 999 123-45-67" : "name@example.com"}
                    placeholderTextColor="#55585d"
                  />
                  <View style={screen.inputNode} />
                </View>
              </View>

              <View style={screen.securityRow}>
                <View style={screen.securityDot} />
                <Text style={screen.securityNote}>Одноразовый код · пароль не нужен</Text>
              </View>
              {error && <ErrorMessage text={error} />}
              <TechButton
                label={busy ? "Отправляем…" : isSignup ? "Создать аккаунт" : "Войти"}
                disabled={busy || !address.trim()}
                onPress={requestCode}
              />

              <ProviderBlock methods={methods} labels={labels} busy={busy} onPress={startOAuth} />
            </View>
          )}

          {!consent && !challenge && (
            <Pressable style={screen.switchMode} onPress={() => showForm(isSignup ? "signin" : "signup")}>
              <Text style={screen.switchModeText}>
                {isSignup ? "Уже есть аккаунт?  " : "Нет аккаунта?  "}
                <Text style={screen.switchModeLink}>{isSignup ? "Войти" : "Зарегистрироваться"}</Text>
              </Text>
            </Pressable>
          )}
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
      <Onboarding
        language="ru"
        onComplete={() => showForm("signup")}
        onSignIn={() => showForm("signin")}
      />
    </>
  );
}

function ProviderBlock({
  methods,
  labels,
  busy,
  onPress,
  compact = false,
}: {
  methods: SignInMethods | null;
  labels: Record<string, string>;
  busy: boolean;
  onPress: (provider: Provider) => void;
  compact?: boolean;
}) {
  if (!methods?.oauth.length) return null;
  return (
    <View style={compact ? screen.providerCompact : screen.providerBlock}>
      <View style={screen.divider}>
        <View style={screen.dividerTick} />
        <Text style={screen.dividerText}>{compact ? "ПРОДОЛЖИТЬ ЧЕРЕЗ" : "ВОЙТИ С ПОМОЩЬЮ"}</Text>
        <View style={screen.dividerTick} />
      </View>
      <View style={screen.providerRow}>
        {methods.oauth.map((provider) => (
          <ProviderAction
            key={provider}
            provider={provider}
            label={labels[provider] ?? provider}
            disabled={busy}
            onPress={() => onPress(provider)}
          />
        ))}
      </View>
    </View>
  );
}

function TechSignal() {
  const pulse = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.delay(350),
        Animated.timing(pulse, {
          toValue: 1,
          duration: 2200,
          easing: Easing.inOut(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.delay(450),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [pulse]);

  return (
    <View style={screen.techSignal} pointerEvents="none">
      <View style={screen.techTrack}>
        <Animated.View
          style={[
            screen.techPulse,
            {
              opacity: pulse.interpolate({ inputRange: [0, 0.12, 0.88, 1], outputRange: [0, 1, 1, 0] }),
              transform: [{ translateX: pulse.interpolate({ inputRange: [0, 1], outputRange: [0, 142] }) }],
            },
          ]}
        />
      </View>
      <Text style={screen.techStatus}>SECURE LINK  /  READY</Text>
    </View>
  );
}

function TechButton({ label, disabled, onPress }: { label: string; disabled: boolean; onPress: () => void }) {
  const scale = useRef(new Animated.Value(1)).current;
  const scan = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.delay(900),
        Animated.timing(scan, {
          toValue: 1,
          duration: 850,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true,
        }),
        Animated.delay(1500),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [scan]);

  const press = (toValue: number) => {
    Animated.spring(scale, { toValue, damping: 18, stiffness: 280, mass: 0.55, useNativeDriver: true }).start();
  };

  return (
    <Animated.View style={[{ transform: [{ scale }] }, disabled && screen.disabled]}>
      <Pressable
        accessibilityRole="button"
        disabled={disabled}
        style={screen.techButton}
        onPress={onPress}
        onPressIn={() => press(0.975)}
        onPressOut={() => press(1)}
      >
        <Text style={screen.techButtonText}>{label}</Text>
        <Text style={screen.techButtonArrow}>↗</Text>
        <Animated.View
          pointerEvents="none"
          style={[
            screen.buttonScanner,
            { transform: [{ translateX: scan.interpolate({ inputRange: [0, 1], outputRange: [-48, 420] }) }] },
          ]}
        />
      </Pressable>
    </Animated.View>
  );
}

function ProviderAction({
  provider,
  label,
  disabled,
  onPress,
}: {
  provider: Provider;
  label: string;
  disabled: boolean;
  onPress: () => void;
}) {
  const scale = useRef(new Animated.Value(1)).current;
  const press = (toValue: number) => {
    Animated.spring(scale, { toValue, damping: 16, stiffness: 320, mass: 0.5, useNativeDriver: true }).start();
  };

  return (
    <Animated.View style={[screen.providerAction, { transform: [{ scale }] }, disabled && screen.disabled]}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={label}
        disabled={disabled}
        style={screen.providerTap}
        onPress={onPress}
        onPressIn={() => press(0.9)}
        onPressOut={() => press(1)}
      >
        <View style={screen.providerHalo} />
        {provider === "yandex" ? <YandexIdIcon /> : <VkIdIcon />}
        <Text style={screen.providerLabel}>{label}</Text>
      </Pressable>
    </Animated.View>
  );
}

function ErrorMessage({ text }: { text: string }) {
  return (
    <View style={screen.errorBox}>
      <Text style={screen.errorIcon}>!</Text>
      <Text style={screen.errorText}>{text}</Text>
    </View>
  );
}

const screen = StyleSheet.create({
  flex: { flex: 1 },
  safeArea: { flex: 1, backgroundColor: "#08090a" },
  welcome: { flex: 1, minHeight: 640, overflow: "hidden", backgroundColor: "#08090a" },
  heroImage: { ...StyleSheet.absoluteFill, width: "100%", height: "100%" },
  heroShade: { ...StyleSheet.absoluteFill, backgroundColor: "rgba(0,0,0,0.08)" },
  welcomeTop: { paddingHorizontal: 28, paddingTop: 20 },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 9, marginBottom: 36 },
  brandMark: {
    width: 30,
    height: 30,
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.accent,
  },
  brandMarkText: { color: "#130a04", fontSize: 16, fontWeight: "900" },
  brandName: { color: colors.text, fontSize: 17, fontWeight: "800", letterSpacing: -0.4 },
  brandAccent: { color: colors.accent },
  welcomeTitle: {
    maxWidth: 330,
    color: "#ffffff",
    fontSize: 34,
    lineHeight: 39,
    fontWeight: "800",
    letterSpacing: -1.1,
  },
  welcomeCopy: {
    maxWidth: 320,
    marginTop: 13,
    color: "#a8a9ac",
    fontSize: 16,
    lineHeight: 23,
  },
  welcomeActions: {
    marginTop: "auto",
    paddingHorizontal: 26,
    paddingBottom: 14,
    gap: 11,
    backgroundColor: "rgba(8,9,10,0.82)",
  },
  primaryButton: {
    width: "100%",
    minHeight: 56,
    borderRadius: 11,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.accent,
  },
  primaryButtonText: { color: "#1b0c04", fontSize: 16, fontWeight: "800" },
  outlineButton: {
    width: "100%",
    minHeight: 54,
    borderWidth: 1,
    borderColor: "#4a4b4e",
    borderRadius: 11,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(18,19,20,0.84)",
  },
  outlineButtonText: { color: "#f2f2f2", fontSize: 16, fontWeight: "700" },
  disabled: { opacity: 0.48 },
  terms: { color: "#797b80", fontSize: 11, lineHeight: 16, textAlign: "center", marginTop: 1 },
  termsLink: { color: "#a8aaad", textDecorationLine: "underline" },
  connectionHint: { alignItems: "center", paddingVertical: 2 },
  connectionHintText: { color: colors.red, fontSize: 12 },
  formScroll: { flex: 1, backgroundColor: "#08090a" },
  formContent: {
    flexGrow: 1,
    width: "100%",
    maxWidth: 560,
    alignSelf: "center",
    paddingHorizontal: 24,
    paddingTop: 10,
    paddingBottom: 28,
  },
  backButton: {
    width: 44,
    height: 44,
    marginLeft: -10,
    alignItems: "center",
    justifyContent: "center",
  },
  backIcon: { color: "#f5f5f5", fontSize: 40, lineHeight: 42, fontWeight: "300" },
  formHeader: { marginTop: 24, marginBottom: 34 },
  formEyebrow: {
    marginBottom: 12,
    color: colors.accent,
    fontSize: 10,
    lineHeight: 14,
    fontWeight: "800",
    letterSpacing: 2.1,
  },
  formTitle: { color: "#ffffff", fontSize: 30, lineHeight: 36, fontWeight: "800", letterSpacing: -0.8 },
  formSubtitle: { maxWidth: 410, marginTop: 12, color: "#96989c", fontSize: 16, lineHeight: 23 },
  techSignal: { marginTop: 22, flexDirection: "row", alignItems: "center", gap: 11 },
  techTrack: { width: 150, height: 1, backgroundColor: "#292b2e" },
  techPulse: {
    position: "absolute",
    top: -2,
    left: 0,
    width: 6,
    height: 5,
    borderRadius: 3,
    backgroundColor: colors.accent,
  },
  techStatus: { color: "#5f6267", fontSize: 9, fontWeight: "700", letterSpacing: 1.35 },
  formStack: { gap: 20 },
  channelTabs: {
    flexDirection: "row",
    gap: 26,
    borderBottomWidth: 1,
    borderBottomColor: "#25272a",
  },
  channelTab: {
    minHeight: 38,
    justifyContent: "center",
    borderBottomWidth: 2,
    borderBottomColor: "transparent",
  },
  channelTabActive: { borderBottomColor: colors.accent },
  channelText: { color: "#66696e", fontSize: 12, fontWeight: "800", letterSpacing: 0.7 },
  channelTextActive: { color: "#f5f5f5" },
  inputShell: {
    minHeight: 59,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    borderWidth: 1,
    borderColor: "#343639",
    borderRadius: 12,
    backgroundColor: "#151617",
  },
  inputIcon: { width: 31, color: "#e2e2e2", fontSize: 20, textAlign: "left" },
  input: { flex: 1, minHeight: 56, color: "#f6f6f6", fontSize: 16, paddingVertical: 0 },
  addressField: { gap: 7 },
  inputLabel: { color: "#6d7075", fontSize: 9, fontWeight: "800", letterSpacing: 1.8 },
  inputRail: {
    minHeight: 52,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: 1,
    borderBottomColor: "#5c5f64",
  },
  addressInput: { flex: 1, minHeight: 50, paddingVertical: 0, color: "#ffffff", fontSize: 19, letterSpacing: -0.2 },
  inputNode: { width: 5, height: 5, borderRadius: 3, backgroundColor: colors.accent },
  codeShell: { justifyContent: "center" },
  codeInput: { textAlign: "center", fontSize: 26, letterSpacing: 10, fontWeight: "700" },
  securityRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: -7 },
  securityDot: { width: 4, height: 4, borderRadius: 2, backgroundColor: colors.accent },
  securityNote: { color: "#74767a", fontSize: 12 },
  inlineLink: { color: colors.accent, fontSize: 14, fontWeight: "700", textAlign: "center", paddingVertical: 8 },
  errorBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
    paddingHorizontal: 13,
    paddingVertical: 12,
    borderWidth: 1,
    borderColor: "rgba(239,93,93,0.35)",
    borderRadius: 11,
    backgroundColor: "rgba(239,93,93,0.08)",
  },
  errorIcon: {
    width: 20,
    height: 20,
    borderRadius: 10,
    overflow: "hidden",
    color: "#180606",
    backgroundColor: colors.red,
    textAlign: "center",
    fontSize: 13,
    fontWeight: "900",
  },
  errorText: { flex: 1, color: "#ef8b8b", fontSize: 13, lineHeight: 19 },
  loadingCard: {
    minHeight: 90,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "#242629",
    borderRadius: 12,
    backgroundColor: "#111213",
  },
  loadingText: { color: "#8c8e92", fontSize: 14 },
  techButton: {
    minHeight: 56,
    overflow: "hidden",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 28,
    backgroundColor: colors.accent,
  },
  techButtonText: { color: "#180b04", fontSize: 15, fontWeight: "900", letterSpacing: 0.15 },
  techButtonArrow: { position: "absolute", right: 21, color: "#180b04", fontSize: 21, fontWeight: "800" },
  buttonScanner: {
    position: "absolute",
    top: -4,
    bottom: -4,
    left: 0,
    width: 2,
    backgroundColor: "rgba(255,255,255,0.42)",
    transform: [{ rotate: "12deg" }],
  },
  divider: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10 },
  dividerTick: { width: 16, height: 1, backgroundColor: "#34373a" },
  dividerText: { color: "#686b70", fontSize: 9, fontWeight: "800", letterSpacing: 1.6 },
  providerBlock: { gap: 14, marginTop: 1 },
  providerCompact: { gap: 11, marginTop: 3 },
  providerRow: { flexDirection: "row", justifyContent: "center", gap: 30 },
  providerAction: { width: 82 },
  providerTap: { minHeight: 76, alignItems: "center", justifyContent: "flex-start", gap: 8 },
  providerHalo: {
    position: "absolute",
    top: -5,
    width: 58,
    height: 58,
    borderRadius: 29,
    borderWidth: 1,
    borderColor: "#303236",
  },
  providerLabel: { color: "#898c91", fontSize: 10, fontWeight: "700", letterSpacing: 0.2 },
  switchMode: { marginTop: "auto", alignItems: "center", paddingTop: 52, paddingBottom: 10 },
  switchModeText: { color: "#888a8e", fontSize: 14 },
  switchModeLink: { color: colors.accent, fontWeight: "700", textDecorationLine: "underline" },
});
