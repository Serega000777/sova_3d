import { PhysicalAiClient } from "@physical-ai/contracts";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { probe } from "@/src/capabilities";
import { DEFAULT_BASE_URL, useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

export default function SignIn() {
  const router = useRouter();
  const { signIn } = useSession();
  const [baseUrl, setBaseUrl] = useState(DEFAULT_BASE_URL);
  const [token, setToken] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const capabilities = probe();

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const client = new PhysicalAiClient({ baseUrl: baseUrl.trim(), token: token.trim() });
      await client.listProjects(workspaceId.trim()); // proves the token and the membership
      await signIn({ baseUrl: baseUrl.trim(), token: token.trim(), workspaceId: workspaceId.trim() });
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.card}>
        <Text style={styles.heading}>Sign in</Text>
        <Text style={styles.muted}>
          Paste the token and workspace id printed by `python -m app.cli create-user`. On a phone,
          the API URL must be your computer&apos;s LAN address — not localhost.
        </Text>
        <Text style={styles.muted}>API URL</Text>
        <TextInput
          style={styles.input}
          value={baseUrl}
          onChangeText={setBaseUrl}
          autoCapitalize="none"
          autoCorrect={false}
          placeholderTextColor={colors.muted}
        />
        <Text style={styles.muted}>Bearer token</Text>
        <TextInput
          style={styles.input}
          value={token}
          onChangeText={setToken}
          placeholder="pai_..."
          autoCapitalize="none"
          autoCorrect={false}
          placeholderTextColor={colors.muted}
        />
        <Text style={styles.muted}>Workspace id</Text>
        <TextInput
          style={styles.input}
          value={workspaceId}
          onChangeText={setWorkspaceId}
          autoCapitalize="none"
          autoCorrect={false}
          placeholderTextColor={colors.muted}
        />
        {error && <Text style={styles.error}>{error}</Text>}
        <Pressable
          style={[styles.button, styles.buttonPrimary, busy && { opacity: 0.6 }]}
          disabled={busy || !token.trim() || !workspaceId.trim()}
          onPress={submit}
        >
          <Text style={styles.buttonText}>{busy ? "Checking…" : "Continue"}</Text>
        </Pressable>
      </View>

      <View style={styles.card}>
        <Text style={styles.heading}>This device</Text>
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
