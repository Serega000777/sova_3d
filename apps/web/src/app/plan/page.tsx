"use client";

/**
 * 2D plan markup (T-237 / F-087): open a flat plan of one room or a whole building and mark
 * it up with pins, revision clouds, shapes, arrows, text and dimensions. Annotations are
 * stored in plan millimetres. When a project is chosen (T-237b), they are shared server-side
 * across devices and viewers; this browser's copy is kept only as an offline/error fallback.
 */
import {
  ANNOTATION_COLOURS,
  type Annotation,
  type AnnotationKind,
  type AnnotationStatus,
  type FloorPlan,
  type Project,
  commit,
  formatLength,
  newHistory,
  parseAnnotations,
  parseFloorPlan,
  appendRoom,
  rectangularRoom,
  redo,
  sampleHouse,
  undo,
  distanceBetween,
  type History,
} from "@physical-ai/contracts";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { PlanEditor, type PlanTool, type PlanUnderlay, exportPlanSvg } from "@/components/PlanEditor";
import { useSession } from "@/lib/session";

/** The markup history, tagged with the plan it belongs to so a save never lands on the wrong plan. */
interface MarkupState {
  planId: string | null;
  history: History<Annotation[]>;
}

type Action =
  | { type: "commit"; next: Annotation[] }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "reset"; planId: string; present: Annotation[] };

function reducer(state: MarkupState, action: Action): MarkupState {
  switch (action.type) {
    case "commit":
      return { ...state, history: commit(state.history, action.next) };
    case "undo":
      return { ...state, history: undo(state.history) };
    case "redo":
      return { ...state, history: redo(state.history) };
    case "reset":
      return { planId: action.planId, history: newHistory(action.present) };
  }
}

const PLAN_KEY = "sova.plan.current";
const PROJECT_KEY = "sova.plan.project";
const notesKey = (planId: string) => `sova.plan.annotations.${planId}`;
/** Server writes are debounced so dragging a shape does not fire a PUT per frame. */
const SYNC_DEBOUNCE_MS = 800;

const TOOLS: { id: PlanTool; icon: string; ru: string; en: string; key: string }[] = [
  { id: "select", icon: "↖", ru: "Выбор", en: "Select", key: "v" },
  { id: "hand", icon: "✋", ru: "Рука", en: "Pan", key: "h" },
  { id: "pin", icon: "📍", ru: "Пин", en: "Pin", key: "p" },
  { id: "cloud", icon: "☁", ru: "Облако", en: "Cloud", key: "c" },
  { id: "rect", icon: "▭", ru: "Прямоугольник", en: "Rectangle", key: "r" },
  { id: "circle", icon: "◯", ru: "Круг", en: "Circle", key: "o" },
  { id: "arrow", icon: "➚", ru: "Стрелка", en: "Arrow", key: "a" },
  { id: "freehand", icon: "✎", ru: "Карандаш", en: "Freehand", key: "f" },
  { id: "text", icon: "T", ru: "Текст", en: "Text", key: "t" },
  { id: "dimension", icon: "↔", ru: "Размер", en: "Dimension", key: "d" },
];

function describe(a: Annotation, ru: boolean): string {
  const names: Record<AnnotationKind, [string, string]> = {
    pin: ["Пин", "Pin"],
    cloud: ["Облако", "Cloud"],
    rect: ["Прямоугольник", "Rectangle"],
    circle: ["Круг", "Circle"],
    arrow: ["Стрелка", "Arrow"],
    freehand: ["Рисунок", "Drawing"],
    text: ["Текст", "Text"],
    dimension: ["Размер", "Dimension"],
  };
  const name = names[a.kind][ru ? 0 : 1];
  if (a.kind === "pin") return `${name} ${a.number}`;
  if (a.kind === "text") return `${name}: ${a.text}`;
  if (a.kind === "dimension") return `${name} ${formatLength(distanceBetween(a.from, a.to))}`;
  return name;
}

function download(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function PlanPage() {
  const { session, client } = useSession();
  const language: "ru" | "en" = "ru";
  const ru = language === "ru";
  const author = session?.displayName || session?.address || (ru ? "Вы" : "You");

  const [plan, setPlan] = useState<FloorPlan>(() => rectangularRoom(4000, 5000, "Комната"));
  const [markup, dispatch] = useReducer(reducer, { planId: null, history: newHistory([] as Annotation[]) });
  const { history } = markup;
  const annotations = history.present;
  const [tool, setTool] = useState<PlanTool>("select");
  const [colour, setColour] = useState<string>(ANNOTATION_COLOURS[0]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | AnnotationStatus>("all");
  const [showGrid, setShowGrid] = useState(true);
  const [underlay, setUnderlay] = useState<PlanUnderlay | null>(null);
  const [fitRevision, setFitRevision] = useState(0);
  const [roomSize, setRoomSize] = useState({ width: 4, depth: 5 });
  const [message, setMessage] = useState<string | null>(null);
  // T-237b: the project whose markup is the source of truth; "" keeps this plan browser-only.
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [baseVersionId, setBaseVersionId] = useState<string | null>(null);
  const [layoutRooms, setLayoutRooms] = useState(3);
  const [layoutBusy, setLayoutBusy] = useState(false);
  const [syncError, setSyncError] = useState(false);
  const syncTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(PROJECT_KEY);
      if (stored) setProjectId(stored);
    } catch {
      // unreadable storage: this plan starts out browser-only
    }
  }, []);

  useEffect(() => {
    if (!client || !session) return;
    client
      .listProjects(session.workspaceId)
      .then(setProjects)
      .catch(() => undefined);
  }, [client, session]);

  const chooseProject = useCallback((id: string) => {
    setProjectId(id);
    setBaseVersionId(null);
    setSyncError(false);
    try {
      if (id) window.localStorage.setItem(PROJECT_KEY, id);
      else window.localStorage.removeItem(PROJECT_KEY);
    } catch {
      // storage full or blocked: the chosen project still works for this visit
    }
  }, []);

  // restore the last plan, then its annotations
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(PLAN_KEY);
      const stored = raw ? parseFloorPlan(JSON.parse(raw)) : null;
      if (stored) setPlan(stored);
    } catch {
      // unreadable storage: keep the default room
    }
  }, []);
  // Load this plan's markup: from the chosen project's server copy when one is chosen (and
  // from this browser's copy otherwise, or if the server call fails).
  useEffect(() => {
    let active = true;
    const localAnnotations = (): Annotation[] => {
      try {
        const raw = window.localStorage.getItem(notesKey(plan.id));
        return raw ? parseAnnotations(JSON.parse(raw)) : [];
      } catch {
        return [];
      }
    };
    if (client && projectId) {
      client
        .getPlanAnnotations(projectId, plan.id)
        .then((out) => {
          if (!active) return;
          dispatch({ type: "reset", planId: plan.id, present: parseAnnotations(out.annotations) });
          setSyncError(false);
        })
        .catch(() => {
          if (!active) return;
          dispatch({ type: "reset", planId: plan.id, present: localAnnotations() });
          setSyncError(true);
        });
    } else {
      dispatch({ type: "reset", planId: plan.id, present: localAnnotations() });
    }
    setSelectedId(null);
    return () => {
      active = false;
    };
  }, [plan, client, projectId]);

  // The browser always keeps its own copy (the fallback for offline use or a failed PUT).
  // When a project is chosen, that copy is also pushed to the server — debounced, since a
  // drag commits many small edits — where it becomes the source of truth for every viewer.
  useEffect(() => {
    if (markup.planId !== plan.id) return; // the history still belongs to the previous plan
    try {
      window.localStorage.setItem(notesKey(plan.id), JSON.stringify(annotations));
    } catch {
      setMessage(ru ? "Не удалось сохранить разметку в браузере." : "Could not save the markup in this browser.");
    }
    if (!client || !projectId) return;
    if (syncTimer.current) clearTimeout(syncTimer.current);
    const planId = plan.id;
    syncTimer.current = setTimeout(() => {
      client
        .putPlanAnnotations(projectId, planId, annotations)
        .then(() => setSyncError(false))
        .catch(() => setSyncError(true));
    }, SYNC_DEBOUNCE_MS);
    return () => {
      if (syncTimer.current) clearTimeout(syncTimer.current);
    };
  }, [annotations, markup.planId, plan.id, client, projectId, ru]);

  // The chosen plan is remembered when it is chosen, not from an effect: effects also run on the
  // initial default plan (and twice under StrictMode) and would overwrite what was restored.
  const choosePlan = useCallback((next: FloorPlan) => {
    setPlan(next);
    try {
      window.localStorage.setItem(PLAN_KEY, JSON.stringify(next));
    } catch {
      // storage full or blocked: the plan still works for this visit
    }
  }, []);

  // A house project opens its server-derived footprint, not the last demo/local plan.
  useEffect(() => {
    if (!client) return;
    const requestedProjectId = new URLSearchParams(window.location.search).get("project_id");
    if (!requestedProjectId) return;
    let active = true;
    chooseProject(requestedProjectId);
    void Promise.all([
      client.getProjectFloorPlan(requestedProjectId),
      client.getProject(requestedProjectId),
    ])
      .then(([loaded, project]) => {
        if (!active) return;
        const parsed = parseFloorPlan(loaded);
        if (!parsed) throw new Error("invalid floor plan");
        choosePlan(parsed);
        setBaseVersionId(project.head_version?.id ?? null);
        setFitRevision((value) => value + 1);
        setMessage(null);
      })
      .catch(() => {
        if (active) {
          setMessage(
            ru
              ? "Для этого проекта пока нет готового 2D-плана."
              : "This project does not have a ready 2D plan yet.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [client, choosePlan, chooseProject, ru]);

  const change = useCallback((next: Annotation[]) => dispatch({ type: "commit", next }), []);
  const selected = annotations.find((a) => a.id === selectedId) ?? null;
  const update = (id: string, patch: Partial<Annotation>) =>
    change(annotations.map((a) => (a.id === id ? ({ ...a, ...patch } as Annotation) : a)));
  const remove = (id: string) => {
    change(annotations.filter((a) => a.id !== id));
    if (selectedId === id) setSelectedId(null);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        dispatch({ type: e.shiftKey ? "redo" : "undo" });
      } else if (mod && e.key.toLowerCase() === "y") {
        e.preventDefault();
        dispatch({ type: "redo" });
      } else if ((e.key === "Delete" || e.key === "Backspace") && selectedId) {
        e.preventDefault();
        remove(selectedId);
      } else if (e.key === "Escape") {
        setSelectedId(null);
        setTool("select");
      } else if (!mod && !e.altKey) {
        const found = TOOLS.find((t) => t.key === e.key.toLowerCase());
        if (found) setTool(found.id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // remove depends on annotations/selectedId; rebinding on each change is cheap
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, annotations]);

  const visible = useMemo(
    () => annotations.filter((a) => filter === "all" || a.status === filter),
    [annotations, filter],
  );
  const open = annotations.filter((a) => a.status === "open").length;

  const loadJson = async (file: File | undefined) => {
    if (!file) return;
    try {
      const parsed = parseFloorPlan(JSON.parse(await file.text()));
      if (!parsed) throw new Error("bad plan");
      choosePlan(parsed);
      setUnderlay(null);
      setFitRevision((n) => n + 1);
      setMessage(null);
    } catch {
      setMessage(ru ? "Не удалось прочитать план: нужен JSON со стенами (walls) или комнатами (rooms)." : "Could not read that plan: it needs a JSON file with walls or rooms.");
    }
  };

  const loadUnderlay = (file: File | undefined) => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      const widthMm = Number(window.prompt(ru ? "Ширина изображения в реальности, мм (например 10000 для 10 м):" : "Real width of the image, mm (e.g. 10000 for 10 m):", "10000"));
      if (!Number.isFinite(widthMm) || widthMm <= 0) return URL.revokeObjectURL(url);
      setUnderlay({ url, widthMm, heightMm: (widthMm * image.naturalHeight) / image.naturalWidth, opacity: 0.6 });
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      setMessage(ru ? "Не удалось открыть изображение." : "Could not open that image.");
    };
    image.src = url;
  };

  const autoLayout = async () => {
    if (!client || !projectId || !baseVersionId || layoutBusy) return;
    setLayoutBusy(true);
    setMessage(null);
    try {
      const result = await client.autoLayoutFloorPlan(projectId, {
        base_version_id: baseVersionId,
        room_count: layoutRooms,
        partition_thickness_mm: 120,
        door_width_mm: 900,
      });
      const parsed = parseFloorPlan(result.floor_plan);
      if (!parsed) throw new Error("invalid floor plan");
      choosePlan(parsed);
      setBaseVersionId(result.version_id);
      setFitRevision((value) => value + 1);
      setMessage(
        ru
          ? `Создана версия v${result.sequence_no}: ${layoutRooms} комнат и соединяющие двери.`
          : `Created v${result.sequence_no}: ${layoutRooms} rooms with connecting doors.`,
      );
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLayoutBusy(false);
    }
  };

  const exportSvg = () => download(`${plan.name}.svg`, new Blob([exportPlanSvg(plan, annotations, underlay).svg], { type: "image/svg+xml" }));
  const exportPng = () => {
    const { svg, width, height } = exportPlanSvg(plan, annotations, underlay);
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = width * 2;
      canvas.height = height * 2;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => blob && download(`${plan.name}.png`, blob), "image/png");
    };
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  };
  const exportJson = () =>
    download(`${plan.name}.markup.json`, new Blob([JSON.stringify({ plan, annotations }, null, 2)], { type: "application/json" }));

  return (
    <div className="plan-page">
      <header className="plan-top">
        <div className="plan-source">
          <strong>{plan.name}</strong>
          <span className="chip">{plan.rooms.length > 1 ? (ru ? `Здание · ${plan.rooms.length} комн.` : `Building · ${plan.rooms.length} rooms`) : ru ? "Одна комната" : "Single room"}</span>
          <label className="plan-field" title={ru ? "Разметка хранится на сервере и видна всем участникам проекта" : "Markup is stored on the server and visible to every project member"}>
            {ru ? "Проект" : "Project"}
            <select className="plan-project-select" value={projectId} onChange={(e) => chooseProject(e.target.value)}>
              <option value="">{ru ? "Только в браузере" : "Browser only"}</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </label>
          {projectId && (
            <span className={`chip ${syncError ? "danger" : ""}`}>
              {syncError ? (ru ? "Не сохранено на сервере" : "Not saved to the server") : ru ? "Синхронизировано" : "Synced"}
            </span>
          )}
        </div>
        <div className="plan-actions">
          <label className="plan-field">
            {ru ? "Комната" : "Room"}
            <input type="number" min={1} max={50} step={0.1} value={roomSize.width} onChange={(e) => setRoomSize({ ...roomSize, width: Number(e.target.value) })} />×
            <input type="number" min={1} max={50} step={0.1} value={roomSize.depth} onChange={(e) => setRoomSize({ ...roomSize, depth: Number(e.target.value) })} />
            м
          </label>
          <button type="button" className="btn" onClick={() => choosePlan(rectangularRoom(roomSize.width * 1000, roomSize.depth * 1000, ru ? "Комната" : "Room"))}>
            {ru ? "Создать" : "Create"}
          </button>
          <button
            type="button"
            className="btn"
            title={ru ? "Добавить комнату справа от плана: так собирается план дома" : "Add a room to the right of the plan to build a house plan"}
            onClick={() => {
              const grown = appendRoom(plan, rectangularRoom(roomSize.width * 1000, roomSize.depth * 1000, ru ? "Комната" : "Room"), 120);
              // two or more rooms are a building; the plan keeps its id, so the markup stays attached
              choosePlan(grown.rooms.length > 1 ? { ...grown, name: ru ? "Дом" : "House" } : grown);
              setFitRevision((n) => n + 1);
            }}
          >
            {ru ? "+ Комната" : "+ Room"}
          </button>
          <button type="button" className="btn" onClick={() => choosePlan(sampleHouse())}>
            {ru ? "Пример: дом" : "Sample house"}
          </button>
          {projectId && baseVersionId && (
            <>
              <label className="plan-field" title={ru ? "Пока поддерживается прямоугольный внешний контур" : "Currently supports a rectangular footprint"}>
                {ru ? "Автоплан" : "Auto layout"}
                <input type="number" min={2} max={8} step={1} value={layoutRooms} onChange={(e) => setLayoutRooms(Number(e.target.value))} />
                {ru ? "комн." : "rooms"}
              </label>
              <button type="button" className="btn primary" disabled={layoutBusy} onClick={() => void autoLayout()}>
                {layoutBusy ? (ru ? "Планируем…" : "Planning…") : ru ? "Создать комнаты" : "Create rooms"}
              </button>
            </>
          )}
          <label className="btn plan-file">
            {ru ? "План (JSON)" : "Plan (JSON)"}
            <input type="file" accept="application/json,.json" onChange={(e) => loadJson(e.target.files?.[0])} />
          </label>
          <label className="btn plan-file">
            {ru ? "Подложка" : "Underlay"}
            <input type="file" accept="image/*" onChange={(e) => loadUnderlay(e.target.files?.[0])} />
          </label>
          {underlay && (
            <>
              <input type="range" min={0.1} max={1} step={0.05} value={underlay.opacity} aria-label={ru ? "Прозрачность подложки" : "Underlay opacity"} onChange={(e) => setUnderlay({ ...underlay, opacity: Number(e.target.value) })} />
              <button type="button" className="btn" onClick={() => setUnderlay(null)}>×</button>
            </>
          )}
        </div>
      </header>

      <div className="plan-body">
        <nav className="plan-tools" aria-label={ru ? "Инструменты разметки" : "Markup tools"}>
          {TOOLS.map((item) => (
            <button key={item.id} type="button" className={`plan-tool ${tool === item.id ? "active" : ""}`} onClick={() => setTool(item.id)} title={`${ru ? item.ru : item.en} (${item.key.toUpperCase()})`} aria-label={ru ? item.ru : item.en}>
              <span aria-hidden="true">{item.icon}</span>
            </button>
          ))}
          <span className="plan-sep" />
          {ANNOTATION_COLOURS.map((c) => (
            <button key={c} type="button" className={`plan-swatch ${colour === c ? "active" : ""}`} style={{ background: c }} aria-label={c} onClick={() => {
              setColour(c);
              if (selected) update(selected.id, { colour: c });
            }} />
          ))}
          <span className="plan-sep" />
          <button type="button" className="plan-tool" disabled={history.past.length === 0} onClick={() => dispatch({ type: "undo" })} title="Ctrl+Z" aria-label={ru ? "Отменить" : "Undo"}>↶</button>
          <button type="button" className="plan-tool" disabled={history.future.length === 0} onClick={() => dispatch({ type: "redo" })} title="Ctrl+Shift+Z" aria-label={ru ? "Повторить" : "Redo"}>↷</button>
          <button type="button" className={`plan-tool ${showGrid ? "active" : ""}`} onClick={() => setShowGrid((v) => !v)} title={ru ? "Сетка 1 м" : "1 m grid"} aria-label={ru ? "Сетка" : "Grid"}>▦</button>
        </nav>

        <div className="plan-stage">
          <PlanEditor
            plan={plan}
            annotations={annotations}
            onChange={change}
            selectedId={selectedId}
            onSelect={setSelectedId}
            tool={tool}
            colour={colour}
            author={author}
            underlay={underlay}
            showGrid={showGrid}
            fitRevision={fitRevision}
            language={language}
          />
          {message && <div className="plan-message" role="alert">{message}</div>}
        </div>

        <aside className="plan-side" aria-label={ru ? "Замечания" : "Annotations"}>
          <div className="plan-side-head">
            <strong>{ru ? "Замечания" : "Annotations"}</strong>
            <span className="chip">{ru ? `открыто ${open}` : `${open} open`}</span>
          </div>
          <div className="plan-filter" role="group">
            {(["all", "open", "resolved"] as const).map((f) => (
              <button key={f} type="button" className={filter === f ? "active" : ""} onClick={() => setFilter(f)}>
                {f === "all" ? (ru ? "Все" : "All") : f === "open" ? (ru ? "Открытые" : "Open") : ru ? "Решённые" : "Resolved"}
              </button>
            ))}
          </div>
          <ul className="plan-list">
            {visible.length === 0 && <li className="plan-empty">{ru ? "Выберите инструмент слева и отметьте место на плане." : "Pick a tool on the left and mark a spot on the plan."}</li>}
            {visible.map((a) => (
              <li key={a.id} className={a.id === selectedId ? "selected" : ""}>
                <button type="button" className="plan-item" onClick={() => setSelectedId(a.id)}>
                  <span className="plan-dot" style={{ background: a.colour }} />
                  <span className="plan-item-title">{describe(a, ru)}</span>
                  <span className={`plan-status ${a.status}`}>{a.status === "open" ? (ru ? "открыто" : "open") : ru ? "решено" : "done"}</span>
                </button>
                {a.id === selectedId && (
                  <div className="plan-item-edit">
                    <textarea rows={3} value={a.note} placeholder={ru ? "Комментарий…" : "Comment…"} onChange={(e) => update(a.id, { note: e.target.value })} />
                    <div className="plan-item-meta">{a.author} · {new Date(a.created_at).toLocaleString(ru ? "ru-RU" : "en-GB")}</div>
                    <div className="plan-item-buttons">
                      <button type="button" className="btn" onClick={() => update(a.id, { status: a.status === "open" ? "resolved" : "open" })}>
                        {a.status === "open" ? (ru ? "Решено" : "Resolve") : ru ? "Открыть снова" : "Reopen"}
                      </button>
                      <button type="button" className="btn danger" onClick={() => remove(a.id)}>{ru ? "Удалить" : "Delete"}</button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
          <div className="plan-export">
            <button type="button" className="btn" onClick={exportPng}>PNG</button>
            <button type="button" className="btn" onClick={exportSvg}>SVG</button>
            <button type="button" className="btn" onClick={exportJson}>JSON</button>
            <button type="button" className="btn" onClick={() => setFitRevision((n) => n + 1)}>{ru ? "Вписать" : "Fit"}</button>
          </div>
        </aside>
      </div>
    </div>
  );
}
