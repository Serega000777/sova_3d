"use client";

import type { Template } from "@physical-ai/contracts";
import { useRouter } from "next/navigation";
import { type ChangeEvent, type FormEvent, useEffect, useRef, useState } from "react";

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

export default function NewProjectPage() {
  const router = useRouter();
  const { session, ready, client } = useSession();
  const [name, setName] = useState("Новая модель");
  const [prompt, setPrompt] = useState("");
  const [format, setFormat] = useState("3mf");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [source, setSource] = useState<"description" | "photo" | "scanner">("description");
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
        query.set("prompt", prompt.trim());
        query.set("auto", "variants"); // the AI proposes sketches first (F-075)
      }
      if (source === "photo") {
        query.set("tool", "photo");
        if (prompt.trim()) query.set("prompt", prompt.trim());
      }
      query.set("format", format);
      router.push(`/projects/${projectId}?${query}`);
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
        <p>Начните с описания, фотографии или скана. Выбранный источник останется рядом с моделью в рабочей области.</p>
      </div>
      <div className="create-source-picker" role="group" aria-label="С чего начать проект">
        <button type="button" className={`create-source ${source === "description" ? "active" : ""}`} aria-pressed={source === "description"} onClick={() => setSource("description")}><span>✦</span><strong>Описание</strong><small>Идея → эскизы → модель</small></button>
        <button type="button" className={`create-source ${source === "photo" ? "active" : ""}`} aria-pressed={source === "photo"} onClick={() => setSource("photo")}><span>▣</span><strong>Загрузить фото</strong><small>Референс, масштаб и AI</small></button>
        <button type="button" className={`create-source ${source === "scanner" ? "active" : ""}`} aria-pressed={source === "scanner"} onClick={() => setSource("scanner")}><span>⌗</span><strong>Включить сканер</strong><small>Оборудование или телефон</small></button>
      </div>
      {source === "scanner" ? (
        <div className="create-scan-options">
          <button className="card create-scan-option" type="button" onClick={() => router.push("/scanner?source=device")}><span>⌗</span><strong>Подключить 3D-сканер</strong><small>Откройте сессию оборудования и перенесите готовую модель в проект.</small><em>Продолжить →</em></button>
          <button className="card create-scan-option" type="button" onClick={() => router.push("/scanner?source=phone")}><span>▣</span><strong>Сканировать телефоном</strong><small>Предмет, комната или дом — выберите сценарий съёмки.</small><em>Продолжить →</em></button>
        </div>
      ) : (
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
      )}
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
