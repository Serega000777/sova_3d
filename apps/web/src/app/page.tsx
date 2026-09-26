"use client";

import type { Component, EnclosureBody, Project, Template } from "@physical-ai/contracts";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { EnclosureCard } from "@/components/EnclosureCard";
import { TemplateGallery } from "@/components/TemplateGallery";
import { useSession } from "@/lib/session";

const MIME: Record<string, string> = {
  stl: "model/stl",
  obj: "model/obj",
  ply: "model/ply",
  glb: "model/gltf-binary",
  gltf: "model/gltf+json",
  "3mf": "model/3mf",
  dae: "model/vnd.collada+xml",
  usdz: "model/vnd.usdz+zip",
  x3d: "model/x3d+xml",
  x3dv: "model/x3d+vrml",
  fbx: "application/vnd.autodesk.fbx",
  wrl: "model/vrml",
  step: "model/step",
  stp: "model/step",
  iges: "model/iges",
  igs: "model/iges",
};

export default function ProjectsPage() {
  const router = useRouter();
  const { session, ready, client } = useSession();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [catalogue, setCatalogue] = useState<Component[]>([]);
  const language: "en" | "ru" =
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru")
      ? "ru"
      : "en";
  const [name, setName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client || !session) return;
    try {
      setProjects(await client.listProjects(session.workspaceId));
      setTemplates(await client.listTemplates());
      setCatalogue(await client.listComponents(undefined, language));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [client, session, language]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /** T-110: a file from another tool becomes a project you can edit. */
  async function importFile(file: File) {
    if (!client || !session) return;
    setBusy(`Uploading ${file.name}`);
    setError(null);
    try {
      const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
      const contentType = MIME[extension];
      if (!contentType) throw new Error(`unsupported file type “.${extension}”`);
      const project = await client.createProject({
        workspace_id: session.workspaceId,
        name: file.name.replace(/\.[^.]+$/, ""),
      });
      const asset = await client.uploadFile(session.workspaceId, file, file.name, contentType);
      setBusy("Importing");
      const accepted = await client.importModel(project.id, { asset_id: asset.id });
      const job = await client.waitForJob(accepted.job_id, {
        onProgress: (update) => setBusy(`Importing · ${update.progress}%`),
      });
      if (job.status !== "succeeded") {
        const detail = job.error as { message?: string } | null;
        throw new Error(detail?.message ?? "the import failed");
      }
      router.push(`/projects/${project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  /** F-070: a template is a project whose first version is already being built. */
  async function startTemplate(template: Template, params: Record<string, number>) {
    if (!client || !session) return;
    setError(null);
    setBusy(language === "ru" ? "Строим…" : "Building…");
    try {
      const started = await client.startFromTemplate({
        workspace_id: session.workspaceId,
        template_id: template.id,
        params,
        language,
      });
      const job = await client.waitForJob(started.job.job_id, {
        onProgress: (update) => setBusy(`${language === "ru" ? "Строим" : "Building"} · ${update.progress}%`),
      });
      if (job.status === "failed") {
        const detail = job.error as { message?: string } | null;
        throw new Error(detail?.message ?? "the template did not build");
      }
      router.push(`/projects/${started.project_id}?template=${template.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  /** F-036: a case for a board is a project of its own — tray and lid, both editable. */
  async function buildEnclosure(body: Omit<EnclosureBody, "workspace_id" | "project_id">) {
    if (!client || !session) return;
    setError(null);
    setBusy(language === "ru" ? "Строим корпус…" : "Building the case…");
    try {
      const accepted = await client.buildEnclosure({ ...body, workspace_id: session.workspaceId });
      const job = await client.waitForJob(accepted.job.job_id, {
        onProgress: (update) =>
          setBusy(`${language === "ru" ? "Строим корпус" : "Building the case"} · ${update.progress}%`),
      });
      if (job.status === "failed") {
        const detail = job.error as { message?: string } | null;
        throw new Error(detail?.message ?? "the case did not build");
      }
      router.push(`/projects/${accepted.project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

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
      <TemplateGallery
        templates={templates}
        language={language}
        disabled={!!busy}
        onStart={startTemplate}
      />
      <EnclosureCard
        components={catalogue}
        language={language}
        disabled={!!busy}
        onBuild={buildEnclosure}
      />
      <div className="card stack">
        <strong>Open a file you already have</strong>
        <p className="muted">
          STL, OBJ, PLY, GLB, glTF, 3MF, COLLADA, USDZ, X3D, VRML, STEP or IGES — from Blender,
          a CAD package or a scanner. The original is kept; the viewport gets a mesh it can
          render.
        </p>
        <input
          type="file"
          className="input"
          accept=".stl,.obj,.ply,.glb,.gltf,.3mf,.dae,.usdz,.x3d,.x3dv,.wrl,.fbx,.step,.stp,.iges,.igs"
          disabled={!!busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void importFile(file);
          }}
        />
        {busy && <span className="muted">{busy}</span>}
      </div>

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
