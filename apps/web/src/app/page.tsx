"use client";

import type { Project } from "@physical-ai/contracts";
import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { useSession } from "@/lib/session";

export default function ProjectsPage() {
  const { session, ready, client } = useSession();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client || !session) return;
    try {
      setProjects(await client.listProjects(session.workspaceId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [client, session]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!client || !session || !name.trim()) return;
    await client.createProject({ workspace_id: session.workspaceId, name: name.trim() });
    setName("");
    await refresh();
  }

  if (!ready) return null;
  if (!session) {
    return (
      <div className="card">
        <p>
          Describe an object, get a model you can edit and print. <Link href="/login">Sign in</Link>{" "}
          to start.
        </p>
      </div>
    );
  }

  return (
    <div className="stack">
      <form className="card row" onSubmit={create}>
        <input
          className="input"
          style={{ maxWidth: 420 }}
          placeholder="New project name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button className="btn primary" type="submit" disabled={!name.trim()}>
          Create project
        </button>
      </form>
      {error && <div className="error">{error}</div>}
      <div className="grid projects">
        {projects?.map((project) => (
          <Link key={project.id} href={`/projects/${project.id}`} className="card">
            <strong>{project.name}</strong>
            <div className="muted">
              {project.head_version_id ? "has model" : "empty"} ·{" "}
              {new Date(project.created_at).toLocaleDateString()}
            </div>
          </Link>
        ))}
        {projects && projects.length === 0 && (
          <div className="muted">No projects yet — create one above.</div>
        )}
      </div>
    </div>
  );
}
