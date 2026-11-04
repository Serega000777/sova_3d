"use client";

import {
  type Me,
  type WorkspaceMember,
  type WorkspaceMemberRole,
  type WorkspaceTask,
  type WorkspaceVersionActivityItem,
  relativeTime,
} from "@physical-ai/contracts";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { LoadingScreen } from "@/components/LoadingScreen";
import { useSession } from "@/lib/session";

type WorkspaceBrief = Me["workspaces"][number];

function formatAssetBytes(bytes: number, language: "ru" | "en"): string {
  if (bytes < 1024) return `${bytes} ${language === "ru" ? "Б" : "B"}`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} ${language === "ru" ? "КБ" : "KB"}`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} ${language === "ru" ? "МБ" : "MB"}`;
}

export default function TeamWorkspacePage() {
  const { session, ready, client, signIn } = useSession();
  const language: "ru" | "en" =
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru")
      ? "ru"
      : "en";
  const ru = language === "ru";
  const [workspace, setWorkspace] = useState<WorkspaceBrief | null>(null);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [tasks, setTasks] = useState<WorkspaceTask[]>([]);
  const [openTaskCount, setOpenTaskCount] = useState(0);
  const [totalTaskCount, setTotalTaskCount] = useState(0);
  const [activity, setActivity] = useState<WorkspaceVersionActivityItem[]>([]);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [taskTitle, setTaskTitle] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [memberEmail, setMemberEmail] = useState("");
  const [memberRole, setMemberRole] = useState<WorkspaceMemberRole>("viewer");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadRevision = useRef(0);

  const load = useCallback(async () => {
    if (!client || !session) return;
    const request = ++loadRevision.current;
    const workspaceId = session.workspaceId;
    setError(null);
    try {
      const me = await client.me();
      if (loadRevision.current !== request) return;
      const current = me.workspaces.find((item) => item.id === workspaceId) ?? null;
      if (!current) throw new Error(ru ? "Рабочее пространство больше недоступно." : "Workspace is no longer available.");
      if (current.kind !== "team") {
        setWorkspace(current);
        setMembers([]);
        setTasks([]);
        setOpenTaskCount(0);
        setTotalTaskCount(0);
        setActivity([]);
        setActivityError(null);
        setLoaded(true);
        return;
      }
      const [nextMembers, taskList, activityResult] = await Promise.all([
        client.listWorkspaceMembers(workspaceId),
        client.listWorkspaceTasks(workspaceId),
        client.listWorkspaceVersionActivity(workspaceId, 12)
          .then((items) => ({ items, error: null as string | null }))
          .catch((reason: unknown) => ({
            items: [] as WorkspaceVersionActivityItem[],
            error: reason instanceof Error ? reason.message : String(reason),
          })),
      ]);
      if (loadRevision.current !== request || session.workspaceId !== workspaceId) return;
      setWorkspace(current);
      setMembers(nextMembers);
      setTasks(taskList.tasks);
      setOpenTaskCount(taskList.open_count);
      setTotalTaskCount(taskList.total_count);
      setActivity(activityResult.items);
      setActivityError(activityResult.error);
      setLoaded(true);
    } catch (reason) {
      if (loadRevision.current === request) {
        setError(reason instanceof Error ? reason.message : String(reason));
        setLoaded(true);
      }
    }
  }, [client, ru, session]);

  useEffect(() => {
    setLoaded(false);
    setWorkspace(null);
    setMembers([]);
    setTasks([]);
    setActivity([]);
    setActivityError(null);
    void load();
    return () => { loadRevision.current += 1; };
  }, [load]);

  async function createTask(event: React.FormEvent) {
    event.preventDefault();
    if (!client || !session || !taskTitle.trim() || busy || workspace?.role === "viewer") return;
    setBusy("create-task");
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
  }

  async function createWorkspace(event: React.FormEvent) {
    event.preventDefault();
    if (!client || !session || !workspaceName.trim() || busy) return;
    setBusy("create-workspace");
    setError(null);
    try {
      const created = await client.createTeamWorkspace({ name: workspaceName.trim() });
      setWorkspaceName("");
      signIn({ ...session, workspaceId: created.id });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function addMember(event: React.FormEvent) {
    event.preventDefault();
    if (!client || !session || workspace?.role !== "owner" || !memberEmail.trim() || busy) return;
    setBusy("add-member");
    setError(null);
    try {
      await client.addWorkspaceMember(session.workspaceId, {
        email: memberEmail.trim(),
        role: memberRole,
      });
      setMemberEmail("");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function changeRole(member: WorkspaceMember, role: WorkspaceMemberRole) {
    if (!client || !session || workspace?.role !== "owner" || member.role === "owner" || busy) return;
    setBusy(member.user_id);
    setError(null);
    try {
      await client.updateWorkspaceMember(session.workspaceId, member.user_id, role);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function removeMember(member: WorkspaceMember) {
    if (!client || !session || workspace?.role !== "owner" || member.role === "owner" || busy) return;
    const label = member.display_name ?? member.email ?? member.user_id;
    if (!window.confirm(ru ? `Удалить доступ для ${label}?` : `Remove access for ${label}?`)) return;
    setBusy(member.user_id);
    setError(null);
    try {
      await client.removeWorkspaceMember(session.workspaceId, member.user_id);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function toggleTask(task: WorkspaceTask) {
    if (!client || !session || busy || workspace?.role === "viewer") return;
    setBusy(task.id);
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
  }

  if (!ready) return <LoadingScreen />;
  if (!session) {
    return (
      <div className="empty-stage">
        <h1>{ru ? "Команда" : "Team"}</h1>
        <Link className="btn primary" href="/login">{ru ? "Войти" : "Sign in"}</Link>
      </div>
    );
  }
  if (!loaded) return <LoadingScreen />;

  if (workspace?.kind !== "team") {
    return (
      <div className="stack" style={{ maxWidth: 760 }}>
        <h1 style={{ margin: 0 }}>{ru ? "Командное пространство" : "Team workspace"}</h1>
        {error && <div className="error">{error}</div>}
        <div className="card stack">
          <strong>{ru ? "Сейчас выбрано личное пространство" : "A personal workspace is selected"}</strong>
          <span className="muted">
            {ru
              ? "Выберите существующее team workspace в настройках или создайте новое здесь."
              : "Select an existing team workspace in Settings or create one here."}
          </span>
          <form className="row" style={{ flexWrap: "wrap" }} onSubmit={createWorkspace}>
            <input
              className="input"
              value={workspaceName}
              maxLength={200}
              placeholder={ru ? "Название команды" : "Team name"}
              aria-label={ru ? "Название новой команды" : "New team name"}
              onChange={(event) => setWorkspaceName(event.target.value)}
              style={{ flex: 1, minWidth: 220 }}
            />
            <button className="btn primary" type="submit" disabled={Boolean(busy) || !workspaceName.trim()}>
              {ru ? "Создать команду" : "Create team"}
            </button>
          </form>
          <Link className="btn primary" href="/settings" style={{ alignSelf: "flex-start" }}>
            {ru ? "Выбрать существующую" : "Select existing"}
          </Link>
        </div>
      </div>
    );
  }

  const tasksManageable = workspace.role !== "viewer";

  return (
    <div className="stack" style={{ maxWidth: 900 }}>
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: 0 }}>{workspace.name}</h1>
          <span className="muted">{ru ? "Командное пространство" : "Team workspace"} · {workspace.role}</span>
        </div>
        <Link className="btn" href="/settings">{ru ? "Сменить пространство" : "Switch workspace"}</Link>
      </div>

      {error && <div className="error">{error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12 }}>
        <div className="card stack"><strong>{members.length}</strong><span className="muted">{ru ? "участников" : "members"}</span></div>
        <div className="card stack"><strong>{openTaskCount}</strong><span className="muted">{ru ? "открытых задач" : "open tasks"}</span></div>
        <div className="card stack"><strong>{totalTaskCount}</strong><span className="muted">{ru ? "задач всего" : "tasks total"}</span></div>
      </div>

      <section className="card stack">
        <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
          <strong>{ru ? "Задачи команды" : "Team tasks"}</strong>
          {!tasksManageable && <span className="chip">{ru ? "только просмотр" : "view only"}</span>}
        </div>
        {tasksManageable && (
          <form className="row" style={{ flexWrap: "wrap" }} onSubmit={createTask}>
            <input
              className="input"
              value={taskTitle}
              maxLength={200}
              placeholder={ru ? "Новая задача" : "New task"}
              aria-label={ru ? "Название новой задачи" : "New task title"}
              onChange={(event) => setTaskTitle(event.target.value)}
              style={{ flex: 1, minWidth: 220 }}
            />
            <button className="btn primary" type="submit" disabled={Boolean(busy) || !taskTitle.trim()}>
              {ru ? "Добавить" : "Add"}
            </button>
          </form>
        )}
        {tasks.length === 0 && <span className="muted">{ru ? "Задач пока нет." : "No tasks yet."}</span>}
        <ul className="list">
          {tasks.map((task) => (
            <li key={task.id} className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
              <span style={{ textDecoration: task.completed ? "line-through" : undefined }}>{task.title}</span>
              <button
                className="btn"
                type="button"
                disabled={!tasksManageable || Boolean(busy)}
                onClick={() => void toggleTask(task)}
              >
                {task.completed ? (ru ? "Вернуть" : "Reopen") : (ru ? "Готово" : "Complete")}
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="card stack">
        <strong>{ru ? "Последние версии" : "Latest versions"}</strong>
        {activityError && (
          <div className="error">
            {ru ? "Активность временно недоступна: " : "Activity is temporarily unavailable: "}{activityError}
          </div>
        )}
        {!activityError && activity.length === 0 && <span className="muted">{ru ? "Новых версий пока нет." : "No versions yet."}</span>}
        <ul className="list">
          {activity.map((item) => (
            <li key={item.version_id} className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
              <span>
                <Link href={`/projects/${item.project_id}`}><strong>{item.project_name}</strong></Link>{" "}
                <span className="muted">· v{item.sequence_no}{item.label ? ` · ${item.label}` : ""}</span>
              </span>
              <span className="muted">
                {item.creator_name ?? (ru ? "неизвестный автор" : "unknown author")} · {formatAssetBytes(item.total_asset_bytes, language)} · {relativeTime(item.created_at, Date.now(), language)}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="card stack">
        <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
          <strong>{ru ? "Участники" : "Members"}</strong>
          {workspace.role !== "owner" && <span className="chip">{ru ? "управляет владелец" : "owner managed"}</span>}
        </div>
        {workspace.role === "owner" && (
          <form className="row" style={{ flexWrap: "wrap", alignItems: "end" }} onSubmit={addMember}>
            <label className="stack" style={{ flex: 1, minWidth: 220 }}>
              <span className="muted">{ru ? "Почта зарегистрированного пользователя" : "Registered user email"}</span>
              <input
                className="input"
                type="email"
                value={memberEmail}
                maxLength={320}
                required
                onChange={(event) => setMemberEmail(event.target.value)}
              />
            </label>
            <label className="stack">
              <span className="muted">{ru ? "Роль" : "Role"}</span>
              <select className="input" value={memberRole} onChange={(event) => setMemberRole(event.target.value as WorkspaceMemberRole)}>
                <option value="admin">admin</option>
                <option value="editor">editor</option>
                <option value="viewer">viewer</option>
              </select>
            </label>
            <button className="btn primary" type="submit" disabled={Boolean(busy) || !memberEmail.trim()}>
              {ru ? "Добавить" : "Add"}
            </button>
          </form>
        )}
        <ul className="list">
          {members.map((member) => (
            <li key={member.user_id} className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
              <span>{member.display_name ?? member.email ?? member.user_id}</span>
              {workspace.role === "owner" && member.role !== "owner" ? (
                <span className="row">
                  <select
                    className="input"
                    value={member.role}
                    aria-label={`${ru ? "Роль" : "Role"}: ${member.display_name ?? member.email ?? member.user_id}`}
                    disabled={Boolean(busy)}
                    onChange={(event) => void changeRole(member, event.target.value as WorkspaceMemberRole)}
                  >
                    <option value="admin">admin</option>
                    <option value="editor">editor</option>
                    <option value="viewer">viewer</option>
                  </select>
                  <button className="btn" type="button" disabled={Boolean(busy)} onClick={() => void removeMember(member)}>
                    {ru ? "Удалить" : "Remove"}
                  </button>
                </span>
              ) : (
                <span className="chip">{member.role}</span>
              )}
            </li>
          ))}
        </ul>
        <span className="muted">
          {ru
            ? "Добавить можно только уже зарегистрированного пользователя. Владелец неизменяем; приглашения по почте не отправляются."
            : "Only an already registered user can be added. The owner is immutable; no email invitation is sent."}
        </span>
      </section>
    </div>
  );
}
