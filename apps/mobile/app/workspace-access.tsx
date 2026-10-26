import type { WorkspaceMember, WorkspaceMemberRole } from "@physical-ai/contracts";
import { useEffect, useState } from "react";
import { Alert, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

const roles: WorkspaceMemberRole[] = ["admin", "editor", "viewer"];

export default function WorkspaceAccessScreen() {
  const { client, session } = useSession();
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [workspace, setWorkspace] = useState<{ name: string; kind: string; role: string } | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<WorkspaceMemberRole>("viewer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!client || !session) return;
    setError(null);
    const me = await client.me();
    const current = me.workspaces.find((item) => item.id === session.workspaceId) ?? null;
    setWorkspace(current);
    if (current?.kind === "team" && current.role === "owner") {
      setMembers(await client.listWorkspaceMembers(session.workspaceId));
    } else {
      setMembers([]);
    }
  };

  useEffect(() => {
    void load().catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
    // session/client change identifies a different authenticated workspace.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, session?.workspaceId]);

  const add = async () => {
    if (!client || !session || !email.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await client.addWorkspaceMember(session.workspaceId, { email: email.trim(), role });
      setEmail("");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const changeRole = async (member: WorkspaceMember, next: WorkspaceMemberRole) => {
    if (!client || !session || busy || member.role === next) return;
    setBusy(true);
    try {
      await client.updateWorkspaceMember(session.workspaceId, member.user_id, next);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const remove = (member: WorkspaceMember) => Alert.alert(
    "Удалить доступ?",
    member.email ?? member.display_name ?? member.user_id,
    [
      { text: "Отмена", style: "cancel" },
      { text: "Удалить", style: "destructive", onPress: () => void (async () => {
        if (!client || !session) return;
        setBusy(true);
        try {
          await client.removeWorkspaceMember(session.workspaceId, member.user_id);
          await load();
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : String(reason));
        } finally {
          setBusy(false);
        }
      })() },
    ],
  );

  const manageable = workspace?.kind === "team" && workspace.role === "owner";
  return (
    <SafeAreaView style={styles.screen}>
      <ScrollView contentContainerStyle={{ padding: 16, gap: 14, maxWidth: 680, width: "100%", alignSelf: "center" }}>
        <Text style={styles.title}>Доступ команды</Text>
        <Text style={styles.muted}>{workspace?.name ?? "Текущее рабочее пространство"}</Text>
        {!manageable ? (
          <Text style={styles.muted}>
            {workspace?.kind === "personal"
              ? "Личное пространство нельзя расшарить. Создайте team workspace, чтобы управлять участниками."
              : "Управлять участниками может только владелец team workspace."}
          </Text>
        ) : (
          <>
            <View style={{ gap: 8 }}>
              <Text style={styles.heading}>Добавить зарегистрированного пользователя</Text>
              <TextInput value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" placeholder="email@example.com" placeholderTextColor={colors.muted} style={styles.input} />
              <View style={styles.row}>
                {roles.map((item) => <Pressable key={item} onPress={() => setRole(item)} style={[styles.chip, role === item && { borderColor: colors.accent }]}><Text style={styles.chipText}>{item}</Text></Pressable>)}
              </View>
              <Pressable disabled={busy || !email.trim()} onPress={() => void add()} style={[styles.button, styles.buttonPrimary, (busy || !email.trim()) && { opacity: 0.5 }]}><Text style={styles.buttonText}>Добавить</Text></Pressable>
            </View>
            {members.map((member) => (
              <View key={member.user_id} style={styles.card}>
                <Text style={styles.heading}>{member.display_name ?? member.email ?? member.user_id}</Text>
                <Text style={styles.muted}>{member.email ?? "Email не указан"}</Text>
                {member.role === "owner" ? <Text style={styles.muted}>owner · доступ владельца неизменяем</Text> : <>
                  <View style={styles.row}>{roles.map((item) => <Pressable key={item} disabled={busy} onPress={() => void changeRole(member, item)} style={[styles.chip, member.role === item && { borderColor: colors.selection }]}><Text style={styles.chipText}>{item}</Text></Pressable>)}</View>
                  <Pressable disabled={busy} onPress={() => remove(member)}><Text style={{ color: colors.red, fontWeight: "700" }}>Удалить доступ</Text></Pressable>
                </>}
              </View>
            ))}
          </>
        )}
        {error ? <Text style={styles.error}>{error}</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}
