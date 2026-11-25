import type { PhysicalAiClient } from "@physical-ai/contracts";
import { useMemo, useRef, useState } from "react";
import { Alert, Pressable, Text, TextInput, View } from "react-native";

import { projectTransferError, projectTransferRequest } from "./project-transfer";
import { colors, styles } from "./theme";

export function ProjectTransferCard({
  client,
  projectId,
  projectName,
  onTransferred,
}: {
  client: PhysicalAiClient;
  projectId: string;
  projectName: string;
  onTransferred: () => void;
}) {
  const [email, setEmail] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirmationOpen = useRef(false);
  const transferInFlight = useRef(false);
  const request = useMemo(
    () => projectTransferRequest(email, confirmation, projectName),
    [confirmation, email, projectName],
  );

  function confirmTransfer() {
    if (busy || confirmationOpen.current || transferInFlight.current) return;
    if (!request.body) {
      setError(request.error);
      return;
    }
    setError(null);
    confirmationOpen.current = true;
    Alert.alert(
      "Передать проект навсегда?",
      "Проект исчезнет из вашей библиотеки вместе со всей историей версий. Отменить передачу после завершения нельзя.",
      [
        { text: "Отмена", style: "cancel", onPress: () => { confirmationOpen.current = false; } },
        {
          text: "Передать",
          style: "destructive",
          onPress: () => {
            confirmationOpen.current = false;
            void transfer(request.body);
          },
        },
      ],
      { cancelable: true, onDismiss: () => { confirmationOpen.current = false; } },
    );
  }

  async function transfer(body: NonNullable<typeof request.body>) {
    if (transferInFlight.current) return;
    transferInFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      await client.transferProject(projectId, body);
      onTransferred();
    } catch (reason) {
      setError(projectTransferError(reason));
    } finally {
      transferInFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <View style={[styles.card, { gap: 12 }]} accessibilityLabel="Передача проекта">
      <View style={{ gap: 4 }}>
        <Text style={styles.heading}>Передать проект</Text>
        <Text style={styles.muted}>
          Только владелец может передать весь проект существующему пользователю SOVA.
        </Text>
        <Text style={[styles.sectionSubtitle, { color: colors.red }]}>
          Необратимо: проект и вся история версий исчезнут из вашей библиотеки.
        </Text>
      </View>
      <TextInput
        accessibilityLabel="Email нового владельца"
        autoCapitalize="none"
        autoComplete="email"
        editable={!busy}
        keyboardType="email-address"
        maxLength={320}
        onChangeText={(value) => { setEmail(value); setError(null); }}
        placeholder="owner@example.com"
        placeholderTextColor={colors.muted}
        style={styles.input}
        value={email}
      />
      <View style={{ gap: 5 }}>
        <Text style={styles.sectionSubtitle}>Введите точное название проекта: {projectName}</Text>
        <TextInput
          accessibilityLabel="Точное название проекта"
          autoCapitalize="none"
          editable={!busy}
          maxLength={200}
          onChangeText={(value) => { setConfirmation(value); setError(null); }}
          placeholder={projectName}
          placeholderTextColor={colors.muted}
          style={styles.input}
          value={confirmation}
        />
      </View>
      {error ? (
        <Text accessibilityLiveRegion="polite" style={[styles.sectionSubtitle, { color: colors.red }]}>
          {error}
        </Text>
      ) : null}
      <Pressable
        accessibilityRole="button"
        disabled={busy}
        onPress={confirmTransfer}
        style={[
          styles.button,
          { borderColor: colors.red },
          busy && { opacity: 0.5 },
        ]}
      >
        <Text style={[styles.buttonText, { color: colors.red }]}>
          {busy ? "Передаём…" : "Передать проект"}
        </Text>
      </Pressable>
    </View>
  );
}
