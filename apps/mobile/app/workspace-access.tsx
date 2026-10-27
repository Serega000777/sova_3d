import type { Me, WorkspaceMember, WorkspaceMemberRole } from "@physical-ai/contracts";
import { useEffect, useMemo, useState } from "react";
import { Alert, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

const roles: WorkspaceMemberRole[] = ["admin", "editor", "viewer"];
type WorkspaceBrief = Me["workspaces"][number];

export default function WorkspaceAccessScreen() {
  const { client, session, selectWorkspace } = useSession();
  const [workspaces, setWorkspaces] = useState<WorkspaceBrief[]>([]);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [projectCount, setProjectCount] = useState<number | null>(null);
  const [workspaceName, setWorkspaceName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<WorkspaceMemberRole>("viewer");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const workspace = useMemo(
    () => workspaces.find((item) => item.id === session?.workspaceId) ?? null,
    [session?.workspaceId, workspaces],
  );

  const load = async () => {
    if (!client || !session) return;
    setError(null);
    const me = await client.me();
    const current = me.workspaces.find((item) => item.id === session.workspaceId) ?? null;
    if (!current) throw new Error("Текущее рабочее пространство больше недоступно.");
    setWorkspaces(me.workspaces);
    const [projects, nextMembers] = await Promise.all([
      client.listProjects(session.workspaceId),
      current.kind === "team"
        ? client.listWorkspaceMembers(session.workspaceId)
        : Promise.resolve([]),
    ]);
    setProjectCount(projects.length);
    setMembers(nextMembers);
  };

  useEffect(() => {
    setProjectCount(null);
    setMembers([]);
    void load().catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
    // A workspace switch replaces session/client and reloads the canonical selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, session?.workspaceId]);

  const createWorkspace = async () => {
    if (!client || !workspaceName.trim() || busy) return;
    setBusy("create");
    setError(null);
    try {
      const created = await client.createTeamWorkspace({ name: workspaceName.trim() });
      setWorkspaceName("");
      await selectWorkspace(created.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  };

  const chooseWorkspace = async (next: WorkspaceBrief) => {
    if (!session || busy || next.id === session.workspaceId) return;
    setBusy(next.id);
    setError(null);
    try {
      await selectWorkspace(next.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  };

  const add = async () => {
    if (!client || !session || !email.trim() || busy) return;
    setBusy("member");
    setError(null);
    try {
      await client.addWorkspaceMember(session.workspaceId, { email: email.trim(), role });
      setEmail("");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  };

  const changeRole = async (member: WorkspaceMember, next: WorkspaceMemberRole) => {
    if (!client || !session || busy || member.role === next) return;
    setBusy(member.user_id);
    try {
      await client.updateWorkspaceMember(session.workspaceId, member.user_id, next);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  };

  const remove = (member: WorkspaceMember) => Alert.alert(
    "Удалить доступ?",
    member.email ?? member.display_name ?? member.user_id,
    [
      { text: "Отмена", style: "cancel" },
      { text: "Удалить", style: "destructive", onPress: () => void (async () => {
        if (!client || !session) return;
        setBusy(member.user_id);
        try {
          await client.removeWorkspaceMember(session.workspaceId, member.user_id);
          await load();
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : String(reason));
        } finally {
          setBusy(null);
        }
      })() },
    ],
  );

  const manageable = workspace?.kind === "team" && workspace.role === "owner";
  return (
    <SafeAreaView style={styles.screen}>
      <ScrollView contentContainerStyle={{ padding: 16, gap: 14, maxWidth: 760, width: "100%", alignSelf: "center" }}>
        <View style={{ gap: 4 }}>
          <Text style={styles.title}>Командное пространство</Text>
          <Text style={styles.muted}>Проекты и участники берутся из выбранного server workspace.</Text>
        </View>

        <View style={[styles.card, { gap: 10 }]}>
          <Text style={styles.heading}>Рабочие пространства</Text>
          {workspaces.map((item) => {
            const selected = item.id === session?.workspaceId;
            return (
              <Pressable
                key={item.id}
                disabled={Boolean(busy)}
                onPress={() => void chooseWorkspace(item)}
                style={[styles.button, selected && { borderColor: colors.accent, backgroundColor: colors.accentWash }]}
              >
                <Text style={styles.buttonText}>{item.name}</Text>
                <Text style={styles.muted}>{item.kind === "team" ? `Команда · ${item.role}` : "Личное"}{selected ? " · выбрано" : ""}</Text>
              </Pressable>
            );
          })}
          <TextInput
            value={workspaceName}
            onChangeText={setWorkspaceName}
            maxLength={200}
            placeholder="Название новой команды"
            placeholderTextColor={colors.muted}
            style={styles.input}
          />
          <Pressable
            disabled={Boolean(busy) || !workspaceName.trim()}
            onPress={() => void createWorkspace()}
            style={[styles.button, styles.buttonPrimary, (busy || !workspaceName.trim()) && { opacity: 0.5 }]}
          >
            <Text style={styles.buttonText}>Создать team workspace</Text>
          </Pressable>
        </View>

        <View style={[styles.card, { gap: 10 }]}>
          <Text style={styles.heading}>{workspace?.name ?? "Текущее пространство"}</Text>
          <View style={[styles.row, { flexWrap: "wrap" }]}>
            <View style={[styles.statusBadge, { backgroundColor: colors.panel2 }]}>
              <Text style={styles.statusText}>{projectCount ?? "—"} проектов</Text>
            </View>
            {workspace?.kind === "team" ? (
              <View style={[styles.statusBadge, { backgroundColor: colors.panel2 }]}>
                <Text style={styles.statusText}>{members.length} участников</Text>
              </View>
            ) : null}
          </View>
          <Text style={styles.muted}>Задачи не показаны: отдельной серверной модели задач пока нет.</Text>
        </View>

        {workspace?.kind === "team" ? (
          <View style={{ gap: 10 }}>
            <Text style={styles.heading}>Участники</Text>
            {manageable ? (
              <View style={[styles.card, { gap: 8 }]}>
                <Text style={styles.heading}>Добавить зарегистрированного пользователя</Text>
                <TextInput value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" placeholder="email@example.com" placeholderTextColor={colors.muted} style={styles.input} />
                <View style={[styles.row, { flexWrap: "wrap" }]}>
                  {roles.map((item) => <Pressable key={item} onPress={() => setRole(item)} style={[styles.chip, role === item && { borderColor: colors.accent }]}><Text style={styles.chipText}>{item}</Text></Pressable>)}
                </View>
                <Pressable disabled={Boolean(busy) || !email.trim()} onPress={() => void add()} style={[styles.button, styles.buttonPrimary, (busy || !email.trim()) && { opacity: 0.5 }]}><Text style={styles.buttonText}>Добавить</Text></Pressable>
              </View>
            ) : (
              <Text style={styles.muted}>Состав команды доступен всем участникам; роли меняет только владелец.</Text>
            )}
            {members.map((member) => (
              <View key={member.user_id} style={styles.card}>
                <Text style={styles.heading}>{member.display_name ?? member.email ?? member.user_id}</Text>
                <Text style={styles.muted}>{member.email ?? "Email не указан"}</Text>
                {member.role === "owner" || !manageable ? (
                  <Text style={styles.muted}>{member.role}</Text>
                ) : (
                  <>
                    <View style={[styles.row, { flexWrap: "wrap" }]}>{roles.map((item) => <Pressable key={item} disabled={Boolean(busy)} onPress={() => void changeRole(member, item)} style={[styles.chip, member.role === item && { borderColor: colors.selection }]}><Text style={styles.chipText}>{item}</Text></Pressable>)}</View>
                    <Pressable disabled={Boolean(busy)} onPress={() => remove(member)}><Text style={{ color: colors.red, fontWeight: "700" }}>Удалить доступ</Text></Pressable>
                  </>
                )}
              </View>
            ))}
          </View>
        ) : (
          <Text style={styles.muted}>Выберите или создайте team workspace, чтобы работать с командой.</Text>
        )}
        {error ? <Text style={styles.error}>{error}</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}
