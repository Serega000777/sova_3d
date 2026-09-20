"use client";

import type { Template } from "@physical-ai/contracts";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { TemplateGallery } from "@/components/TemplateGallery";
import { useSession } from "@/lib/session";

const IDEAS = [
  "Функциональная деталь с точными размерами",
  "Персонаж или фигурка по описанию",
  "Корпус для электроники",
  "Органайзер или предмет для дома",
];

export default function NewProjectPage() {
  const router = useRouter();
  const { session, ready, client } = useSession();
  const [name, setName] = useState("Новая модель");
  const [prompt, setPrompt] = useState("");
  const [format, setFormat] = useState("3mf");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const language: "en" | "ru" =
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru")
      ? "ru"
      : "en";

  useEffect(() => {
    if (!client) return;
    void client.listTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, [client]);

  /** F-070: a template is a project whose first version is already being built. */
  async function startTemplate(template: Template, params: Record<string, number>) {
    if (!client || !session) return;
    setError(null);
    setBusy(true);
    try {
      const started = await client.startFromTemplate({
        workspace_id: session.workspaceId,
        template_id: template.id,
        params,
        language,
      });
      router.push(`/projects/${started.project_id}?template=${template.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBusy(false);
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!client || !session || !name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const project = await client.createProject({
        workspace_id: session.workspaceId,
        name: name.trim(),
        description: prompt.trim() || null,
      });
      const query = new URLSearchParams();
      if (prompt.trim()) {
        query.set("prompt", prompt.trim());
        query.set("auto", "variants"); // the AI proposes sketches first (F-075)
      }
      query.set("format", format);
      router.push(`/projects/${project.id}?${query}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBusy(false);
    }
  }

  if (!ready) return null;
  if (!session) return <div className="empty-stage"><h1>Сначала войдите</h1><button className="btn primary" onClick={() => router.push("/login")}>Перейти ко входу</button></div>;

  return (
    <div className="create-studio">
      <div className="create-intro">
        <span className="eyebrow">НОВЫЙ ПРОЕКТ</span>
        <h1>Что будем создавать?</h1>
        <p>Опишите идею. В рабочей области можно будет приложить изображение, получить варианты, выделить область и попросить AI изменить только её.</p>
      </div>
      <form className="create-grid" onSubmit={create}>
        <section className="card create-main">
          <label><span>Название проекта</span><input className="input" value={name} onChange={(event) => setName(event.target.value)} maxLength={200} /></label>
          <label><span>Задание для AI</span><textarea className="input creation-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Например: создай 3D-модель брони в стиле высокотехнологичного героя, сначала предложи несколько вариантов силуэта…" /></label>
          <div className="idea-chips">{IDEAS.map((idea) => <button type="button" className="chip" key={idea} onClick={() => setPrompt(idea)}>{idea}</button>)}</div>
        </section>
        <aside className="card create-options">
          <strong>Результат</strong>
          <label><span>Основной формат</span><select className="input" value={format} onChange={(event) => setFormat(event.target.value)}><option value="3mf">3MF · печать</option><option value="stl">STL · универсальный</option><option value="step">STEP · CAD</option><option value="glb">GLB · сцена / web</option><option value="obj">OBJ · графика</option></select></label>
          <div className="creation-mode"><span>✦</span><div><strong>AI-концепция</strong><p className="muted">Описание откроется в чате рабочей области. Перед применением доступны варианты и preview.</p></div></div>
          <div className="creation-mode"><span>⌁</span><div><strong>Изображение</strong><p className="muted">Добавьте фото уже в редакторе — оригинал сохранится как источник.</p></div></div>
          {error && <div className="error">{error}</div>}
          <button className="btn primary create-submit" disabled={busy || !name.trim()}>{busy ? "Создаём…" : "Открыть рабочую область →"}</button>
        </aside>
      </form>
      <div className="create-intro" style={{ marginTop: 32 }}>
        <span className="eyebrow">{language === "ru" ? "ИЛИ НАЧНИТЕ С ШАБЛОНА" : "OR START FROM A TEMPLATE"}</span>
        <p className="muted">
          {language === "ru"
            ? "Готовые детали, которые точно построятся: поменяйте числа и нажмите «Начать»."
            : "Ready parts that always build: change the numbers and press Start."}
        </p>
      </div>
      <TemplateGallery templates={templates} language={language} disabled={busy} onStart={startTemplate} />
    </div>
  );
}
