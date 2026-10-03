"use client";

import {
  type CreateScenario,
  type ProjectGoal,
  type Template,
  getProjectGoal,
  scenarioPath,
} from "@physical-ai/contracts";
import { useRouter, useSearchParams } from "next/navigation";
import { type ChangeEvent, type FormEvent, Suspense, useEffect, useRef, useState } from "react";

import { CreateHub } from "@/components/CreateHub";
import { HouseBoxWizard } from "@/components/HouseBoxWizard";
import { TemplateGallery } from "@/components/TemplateGallery";
import { shrinkPhoto } from "@/lib/photo";
import { saveReferenceImage, type ReferenceImageRecord } from "@/lib/reference-image";
import { useSession } from "@/lib/session";

const IDEAS = [
  "Функциональная деталь с точными размерами",
  "Персонаж или фигурка по описанию",
  "Корпус для электроники",
  "Органайзер или предмет для дома",
];

function NewProjectContent() {
  const router = useRouter();
  const requestedScenario = useSearchParams().get("scenario");
  const { session, ready, client } = useSession();
  const [name, setName] = useState("Новая модель");
  const [prompt, setPrompt] = useState("");
  const [format, setFormat] = useState("3mf");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [goal, setGoal] = useState<ProjectGoal | null>(null);
  const [source, setSource] = useState<"description" | "photo">("description");
  const [photo, setPhoto] = useState<File | null>(null);
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const photoInput = useRef<HTMLInputElement>(null);
  const createdProjectId = useRef<string | null>(null);
  const language: "en" | "ru" =
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru")
      ? "ru"
      : "en";

  useEffect(() => {
    if (!client) return;
    void client.listTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, [client]);

  useEffect(() => {
    if (!photo) { setPhotoUrl(null); return; }
    const url = URL.createObjectURL(photo);
    setPhotoUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  function choosePhoto(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) { setError("Выберите файл изображения."); return; }
    setError(null);
    setPhoto(file);
    setSource("photo");
  }

  /** T-231: a goal picks defaults and a real workflow, but never becomes a project lock. */
  function chooseGoal(chosen: ProjectGoal) {
    if (chosen.source === "scan" && chosen.scanSubject) {
      router.push(`/scanner?source=phone&subject=${chosen.scanSubject}`);
      return;
    }
    setGoal(chosen);
    createdProjectId.current = null;
    setName(chosen.defaultName[language]);
    setPrompt(chosen.defaultPrompt[language]);
    setFormat(chosen.format);
    setSource(chosen.source === "photo" ? "photo" : "description");
    setPhoto(null);
    setError(null);
  }

  /** A Create-menu scenario: scans open the capture flow, pages open their page, the rest start a project. */
  function chooseScenario(scenario: CreateScenario) {
    const target = scenario.goal ? getProjectGoal(scenario.goal) : null;
    if (scenario.route) {
      router.push(scenarioPath(scenario));
    } else if (target) {
      chooseGoal(target);
    }
  }

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
      const projectId = createdProjectId.current ?? (await client.createProject({
        workspace_id: session.workspaceId,
        name: name.trim(),
        description: prompt.trim() || null,
      })).id;
      createdProjectId.current = projectId;
      if (source === "photo" && photo) {
        const blob = await shrinkPhoto(photo);
        const bitmap = await createImageBitmap(blob);
        const widthPx = bitmap.width;
        const heightPx = bitmap.height;
        bitmap.close();
        const record: ReferenceImageRecord = {
          blob, widthPx, heightPx, widthMm: 200, knownMm: 0,
          calibration: [], offsetX: 0, offsetZ: 0, opacity: 0.65, visible: true,
        };
        const asset = await client.uploadFile(session.workspaceId, blob, `${photo.name.replace(/\.[^.]+$/, "")}.jpg`, "image/jpeg");
        await client.putProjectReference(projectId, {
          asset_id: asset.id, width_px: widthPx, height_px: heightPx,
          width_mm: record.widthMm, known_mm: 0, calibration: [],
          offset_x: 0, offset_z: 0, opacity: record.opacity, visible: true,
        });
        // Keep an offline copy as well; the Studio reads it if the signed URL expires.
        await saveReferenceImage(projectId, record).catch(() => undefined);
      }
      const query = new URLSearchParams();
      if (prompt.trim() && source === "description") {
        if (goal?.workflow === "organic") {
          query.set("tool", "shape");
          query.set("organicPrompt", prompt.trim());
        } else {
          query.set("prompt", prompt.trim());
          query.set("auto", "variants"); // the AI proposes sketches first (F-075)
        }
      }
      if (source === "photo") {
        query.set("tool", "photo");
        if (prompt.trim()) query.set("prompt", prompt.trim());
      }
      if (goal) query.set("goal", goal.id);
      query.set("format", format);
      router.push(`/projects/${projectId}?${query}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBusy(false);
    }
  }

  if (!ready) return null;
  if (!session) return <div className="empty-stage"><h1>Сначала войдите</h1><button className="btn primary" onClick={() => router.push("/login")}>Перейти ко входу</button></div>;
  if (goal?.id === "house_design" && client) {
    return (
      <HouseBoxWizard
        client={client}
        workspaceId={session.workspaceId}
        language={language}
        onBack={() => setGoal(null)}
      />
    );
  }

  if (!goal) {
    return (
      <div className="create-studio">
        <div className="create-intro">
          <span className="eyebrow">{language === "ru" ? "СОЗДАТЬ" : "CREATE"}</span>
          <h1>{language === "ru" ? "Что вы хотите создать?" : "What do you want to create?"}</h1>
          <p>{language === "ru" ? "Выберите готовый сценарий: инструменты, подсказки и форматы подстроятся под него." : "Pick a ready scenario: tools, guidance and formats adapt to it."}</p>
        </div>
        <CreateHub language={language} initialScenario={requestedScenario} onChoose={chooseScenario} />
        <div className="create-intro" style={{ marginTop: 16 }}>
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

  return (
    <div className="create-studio">
      <div className="create-intro">
        <span className="eyebrow">НОВЫЙ ПРОЕКТ</span>
        <h1>{goal.title[language]}</h1>
        <p>{goal.note[language]} Это стартовые настройки: проект не привязан к выбранному направлению.</p>
      </div>
      <div className="create-goal-summary card">
        <span aria-hidden="true">{goal.icon}</span>
        <div><strong>{goal.title[language]}</strong><small>{goal.note[language]}</small></div>
        <button type="button" className="btn" onClick={() => setGoal(null)}>← Изменить направление</button>
      </div>
      <form className="create-grid" onSubmit={create}>
        <section className="card create-main">
          <label><span>Название проекта</span><input className="input" value={name} onChange={(event) => setName(event.target.value)} maxLength={200} /></label>
          {source === "photo" && <div className="create-photo-field">
            <input ref={photoInput} type="file" accept="image/*" className="visually-hidden" onChange={choosePhoto} aria-label="Выбрать фотографию" />
            <button type="button" className="create-photo-drop" onClick={() => photoInput.current?.click()}>
              {photoUrl ? <img src={photoUrl} alt="Выбранный референс" /> : <span className="create-photo-symbol">＋</span>}
              <strong>{photo ? "Заменить фото" : "Выбрать фото с устройства"}</strong>
              <small>{photo?.name ?? "JPG, PNG, HEIC или другое изображение, которое открывает браузер"}</small>
            </button>
            <p className="muted">Фото сохранится в проекте. В редакторе можно совместить его с моделью, задать масштаб и передать в AI.</p>
          </div>}
          <label><span>{source === "photo" ? "Что моделировать по фото (необязательно)" : "Задание для AI"}</span><textarea className="input creation-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={source === "photo" ? "Например: оставь форму корпуса, добавь крепление; известная ширина — 80 мм" : "Например: создай 3D-модель брони в стиле высокотехнологичного героя, сначала предложи несколько вариантов силуэта…"} /></label>
          {source === "description" && <div className="idea-chips">{IDEAS.map((idea) => <button type="button" className="chip" key={idea} onClick={() => setPrompt(idea)}>{idea}</button>)}</div>}
        </section>
        <aside className="card create-options">
          <strong>Результат</strong>
          <label><span>Основной формат</span><select className="input" value={format} onChange={(event) => setFormat(event.target.value)}><option value="3mf">3MF · печать</option><option value="stl">STL · универсальный</option><option value="step">STEP · CAD</option><option value="glb">GLB · сцена / web</option><option value="obj">OBJ · графика</option></select></label>
          <div className="creation-mode"><span>{source === "photo" ? "▣" : "✦"}</span><div><strong>{source === "photo" ? "Фото-референс" : "AI-концепция"}</strong><p className="muted">{source === "photo" ? "Фото откроется в инструменте «Референс»: настройте масштаб и создайте модель с AI." : "Описание откроется в чате рабочей области. Перед применением доступны варианты и preview."}</p></div></div>
          {error && <div className="error">{error}</div>}
          {error && createdProjectId.current && <button className="btn" type="button" onClick={() => router.push(`/projects/${createdProjectId.current}?tool=photo`)}>Открыть созданный проект →</button>}
          <button className="btn primary create-submit" disabled={busy || !name.trim() || (source === "photo" && !photo)}>{busy ? "Создаём…" : source === "photo" ? "Создать проект с фото →" : "Открыть рабочую область →"}</button>
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

/** useSearchParams needs a Suspense boundary for the static build. */
export default function NewProjectPage() {
  return (
    <Suspense fallback={null}>
      <NewProjectContent />
    </Suspense>
  );
}
