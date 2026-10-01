"use client";

import {
  type Component,
  type EnclosureBody,
  type LibraryFilter,
  type Listing,
  type LibrarySort,
  type Project,
  type Template,
  isDraft,
  libraryView,
  relativeTime,
} from "@physical-ai/contracts";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EnclosureCard } from "@/components/EnclosureCard";
import { ListingCard } from "@/components/ListingCard";
import { Onboarding } from "@/components/Onboarding";
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
  abc: "application/x-alembic",
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
  const [explore, setExplore] = useState<Listing[]>([]);
  const language: "en" | "ru" =
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru")
      ? "ru"
      : "en";
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<LibrarySort>("updated");
  const [filter, setFilter] = useState<LibraryFilter>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client || !session) return;
    try {
      setProjects(await client.listProjects(session.workspaceId));
      setTemplates(await client.listTemplates());
      setCatalogue(await client.listComponents(undefined, language));
      // the shelf is a nicety: a failure there must not hide the library
      setExplore(await client.searchListings({ sort: "popular", limit: 6 }).catch(() => []));
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

  const visible = useMemo(
    () => (projects ? libraryView(projects, { query, sort, filter }) : []),
    [projects, query, sort, filter],
  );
  const ru = language === "ru";

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
    <div className="stack library">
      <Onboarding language={language} />
      <header className="library-head">
        <h1>{ru ? "Библиотека" : "Library"}</h1>
        <Link href="/new" className="btn primary library-create">
          {ru ? "+ Создать" : "+ Create"}
        </Link>
      </header>
      <div className="library-tools">
        <input
          className="input library-search"
          type="search"
          placeholder={ru ? "Поиск по названию и описанию" : "Search by name or description"}
          aria-label={ru ? "Поиск" : "Search"}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <div className="segmented compact" role="group" aria-label={ru ? "Фильтр" : "Filter"}>
          {(["all", "models", "drafts"] as const).map((item) => (
            <button key={item} type="button" className={filter === item ? "active" : ""} onClick={() => setFilter(item)}>
              {item === "all" ? (ru ? "Все" : "All") : item === "models" ? (ru ? "С моделью" : "With model") : ru ? "Черновики" : "Drafts"}
            </button>
          ))}
        </div>
        <select className="input library-sort" value={sort} aria-label={ru ? "Сортировка" : "Sort"} onChange={(event) => setSort(event.target.value as LibrarySort)}>
          <option value="updated">{ru ? "Недавно изменённые" : "Recently updated"}</option>
          <option value="created">{ru ? "Недавно созданные" : "Recently created"}</option>
          <option value="name">{ru ? "По названию" : "By name"}</option>
        </select>
      </div>
      {error && <div className="error">{error}</div>}
      <div className="library-grid" role="list">
        {visible.map((project) => (
          <Link key={project.id} href={`/projects/${project.id}`} className="library-card" role="listitem">
            <span className={`library-thumb ${isDraft(project) ? "draft" : ""}`} aria-hidden="true">
              {isDraft(project) ? "◌" : "◈"}
            </span>
            <strong>{project.name}</strong>
            <small>
              {isDraft(project) ? (ru ? "Черновик" : "Draft") : ru ? "Есть модель" : "Has a model"} ·{" "}
              {relativeTime(project.updated_at ?? project.created_at, Date.now(), language)}
            </small>
          </Link>
        ))}
        {projects && projects.length > 0 && visible.length === 0 && (
          <p className="muted">{ru ? "Ничего не найдено. Измените поиск или фильтр." : "Nothing matches. Change the search or filter."}</p>
        )}
        {projects && projects.length === 0 && (
          <div className="library-empty">
            <p>{ru ? "Здесь появятся ваши сканы и модели." : "Your scans and models will appear here."}</p>
            <Link href="/new" className="btn primary">{ru ? "Начать" : "Start"}</Link>
          </div>
        )}
      </div>
      {explore.length > 0 && (
        <section className="library-explore" aria-label={ru ? "Исследовать" : "Explore"}>
          <header>
            <h2>{ru ? "Исследовать" : "Explore"}</h2>
            <Link href="/market">{ru ? "Посмотреть все →" : "See all →"}</Link>
          </header>
          <div className="library-explore-row">
            {explore.map((listing) => (
              <ListingCard key={listing.id} listing={listing} />
            ))}
          </div>
        </section>
      )}
      <details className="library-more">
        <summary>{ru ? "Шаблоны, корпуса и импорт файла" : "Templates, enclosures and file import"}</summary>
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
          STL, OBJ, PLY, GLB, glTF, 3MF, COLLADA, USDZ, X3D, VRML, FBX, Alembic, STEP or IGES — from Blender,
          a CAD package or a scanner. The original is kept; the viewport gets a mesh it can
          render.
        </p>
        <input
          type="file"
          className="input"
          accept=".stl,.obj,.ply,.glb,.gltf,.3mf,.dae,.usdz,.x3d,.x3dv,.wrl,.fbx,.abc,.step,.stp,.iges,.igs"
          disabled={!!busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void importFile(file);
          }}
        />
        {busy && <span className="muted">{busy}</span>}
      </div>

      </details>
    </div>
  );
}
