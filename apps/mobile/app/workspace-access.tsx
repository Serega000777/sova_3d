import type {
  Me,
  WorkspaceMember,
  WorkspaceMemberRole,
  WorkspaceTask,
  WorkspaceVersionActivityItem,
} from "@physical-ai/contracts";
import { relativeTime } from "@physical-ai/contracts";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

const roles: WorkspaceMemberRole[] = ["admin", "editor", "viewer"];
type WorkspaceBrief = Me["workspaces"][number];

function formatAssetBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

export default function WorkspaceAccessScreen() {
  const { client, session, selectWorkspace } = useSession();
  const router = useRouter();
  const [workspaces, setWorkspaces] = useState<WorkspaceBrief[]>([]);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [tasks, setTasks] = useState<WorkspaceTask[]>([]);
  const [activity, setActivity] = useState<WorkspaceVersionActivityItem[]>([]);
  const [activityLoaded, setActivityLoaded] = useState(false);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [openTaskCount, setOpenTaskCount] = useState<number | null>(null);
  const [projectCount, setProjectCount] = useState<number | null>(null);
  const [workspaceName, setWorkspaceName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<WorkspaceMemberRole>("viewer");
  const [taskTitle, setTaskTitle] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadRevision = useRef(0);
  const workspace = useMemo(
    () => workspaces.find((item) => item.id === session?.workspaceId) ?? null,
    [session?.workspaceId, workspaces],
  );

  const load = async () => {
    if (!client || !session) return;
    const request = ++loadRevision.current;
    const workspaceId = session.workspaceId;
    setError(null);
    try {
      const me = await client.me();
      if (loadRevision.current !== request) return;
      const current = me.workspaces.find((item) => item.id === workspaceId) ?? null;
      if (!current) throw new Error("Текущее рабочее пространство больше недоступно.");
      const [projects, nextMembers, taskList, activityResult] = await Promise.all([
        client.listProjects(workspaceId),
        current.kind === "team"
          ? client.listWorkspaceMembers(workspaceId)
          : Promise.resolve([]),
        current.kind === "team"
          ? client.listWorkspaceTasks(workspaceId)
          : Promise.resolve({ open_count: 0, total_count: 0, tasks: [] }),
        current.kind === "team"
          ? client.listWorkspaceVersionActivity(workspaceId, 12)
            .then((items) => ({ items, error: null as string | null }))
            .catch((reason: unknown) => ({
              items: [] as WorkspaceVersionActivityItem[],
              error: reason instanceof Error ? reason.message : String(reason),
            }))
          : Promise.resolve({ items: [] as WorkspaceVersionActivityItem[], error: null }),
      ]);
      if (loadRevision.current !== request) return;
      setWorkspaces(me.workspaces);
      setProjectCount(projects.length);
      setMembers(nextMembers);
      setOpenTaskCount(current.kind === "team" ? taskList.open_count : null);
      setTasks(taskList.tasks);
      setActivity(activityResult.items);
      setActivityLoaded(current.kind === "team" && activityResult.error === null);
      setActivityError(activityResult.error);
    } catch (reason) {
      if (loadRevision.current === request) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    }
  };

  useEffect(() => {
    setProjectCount(null);
    setMembers([]);
    setTasks([]);
    setOpenTaskCount(null);
    setActivity([]);
    setActivityLoaded(false);
    setActivityError(null);
    void load();
    // A workspace switch replaces session/client and reloads the canonical selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    return () => { loadRevision.current += 1; };
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
  const tasksManageable = workspace?.kind === "team" && workspace.role !== "viewer";

  const createTask = async () => {
    if (!client || !session || !tasksManageable || !taskTitle.trim() || busy) return;
    setBusy("task-create");
    setError(null);
    try {
      await client.createWorkspaceTask(session.workspaceId, { title: taskTitle.trim() });
      setTaskTitle("");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  };

  const toggleTask = async (task: WorkspaceTask) => {
    if (!client || !session || !tasksManageable || busy) return;
    setBusy(`task-${task.id}`);
    setError(null);
    try {
      await client.updateWorkspaceTask(session.workspaceId, task.id, {
        expected_revision: task.revision,
        completed: !task.completed,
      });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  };
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
            {workspace?.kind === "team" ? (
              <View style={[styles.statusBadge, { backgroundColor: colors.panel2 }]}>
                <Text style={styles.statusText}>{openTaskCount ?? "—"} открытых задач</Text>
              </View>
            ) : null}
          </View>
        </View>

        {workspace?.kind === "team" ? (
          <View style={{ gap: 10 }} accessibilityLabel="Последние версии команды">
            <Text style={styles.heading}>Активность команды</Text>
            <Text style={styles.muted}>Финализированные immutable-версии проектов выбранного workspace.</Text>
            {activityLoaded ? activity.length > 0 ? activity.map((item) => (
              <Pressable
                key={item.version_id}
                accessibilityRole="button"
                onPress={() => router.push(`/project/${item.project_id}`)}
                style={[styles.card, { gap: 3 }]}
              >
                <Text style={styles.heading}>{item.project_name} · v{item.sequence_no}</Text>
                <Text style={styles.muted}>
                  {item.label ?? "Без названия"} · {item.creator_name ?? "Система"} · {relativeTime(item.created_at, Date.now(), "ru")}
                </Text>
                <Text style={styles.muted}>{formatAssetBytes(item.total_asset_bytes)}</Text>
              </Pressable>
            )) : (
              <Text style={styles.muted}>Финализированных версий пока нет.</Text>
            ) : activityError ? (
              <View style={[styles.card, { gap: 3, borderColor: colors.yellow }]}>
                <Text style={styles.heading}>Лента версий недоступна</Text>
                <Text style={styles.muted}>{activityError}</Text>
              </View>
            ) : (
              <Text style={styles.muted}>Загрузка активности…</Text>
            )}
          </View>
        ) : null}

        {workspace?.kind === "team" ? (
          <View style={{ gap: 10 }}>
            <Text style={styles.heading}>Задачи команды</Text>
            {tasksManageable ? (
              <View style={[styles.card, { gap: 8 }]}>
                <TextInput
                  value={taskTitle}
                  onChangeText={setTaskTitle}
                  maxLength={300}
                  placeholder="Новая задача"
                  placeholderTextColor={colors.muted}
                  style={styles.input}
                />
                <Pressable
                  disabled={Boolean(busy) || !taskTitle.trim()}
                  onPress={() => void createTask()}
                  style={[styles.button, styles.buttonPrimary, (busy || !taskTitle.trim()) && { opacity: 0.5 }]}
                >
                  <Text style={styles.buttonText}>Добавить задачу</Text>
                </Pressable>
              </View>
            ) : (
              <Text style={styles.muted}>Viewer видит задачи, но не может менять их.</Text>
            )}
            {tasks.length === 0 ? <Text style={styles.muted}>Задач пока нет.</Text> : null}
            {tasks.slice(0, 12).map((task) => (
              <Pressable
                key={task.id}
                accessibilityRole="checkbox"
                accessibilityState={{ checked: task.completed, disabled: !tasksManageable || Boolean(busy) }}
                disabled={!tasksManageable || Boolean(busy)}
                onPress={() => void toggleTask(task)}
                style={[styles.card, styles.row, task.completed && { opacity: 0.62 }]}
              >
                <Text style={{ color: task.completed ? colors.green : colors.accent, fontSize: 20 }}>
                  {task.completed ? "✓" : "○"}
                </Text>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={[styles.heading, task.completed && { textDecorationLine: "line-through" }]}>{task.title}</Text>
                  <Text style={styles.muted}>rev {task.revision}{task.completed ? " · выполнено" : " · открыто"}</Text>
                </View>
              </Pressable>
            ))}
            {tasks.length > 12 ? <Text style={styles.muted}>Показаны первые 12 задач из {tasks.length} загруженных.</Text> : null}
          </View>
        ) : null}

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
