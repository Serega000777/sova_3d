/**
 * F-084 follow-up: one "Create" menu for web, desktop, tablet and mobile.
 *
 * A scenario is a ready path — room scan, object scan, building from outside, AI model, a part
 * to print — that opens the right tool with the right guidance and processing defaults, so a
 * person never has to learn the universal editor first. The registry is data: every client
 * draws the same groups, the same preparation checklist and the same processing choices.
 */
import type { ProjectGoalId } from "./project-goals.js";

export type ScenarioGroup = "scan" | "generate" | "model" | "bring";
export type Bilingual = { ru: string; en: string };

export interface GuideStep {
  title: Bilingual;
  /** Short, concrete advice; shown as a checklist. */
  tips: Bilingual[];
}

export interface CaptureLimits {
  /** Fewest frames the reconstruction accepts (the API refuses fewer). */
  minFrames: number;
  /** Where the progress bar ends: a guide for a good result, not the API's hard cap. */
  maxFrames: number;
}

export interface CreateScenario {
  id: string;
  group: ScenarioGroup;
  icon: string;
  title: Bilingual;
  note: Bilingual;
  /** The project goal whose defaults this scenario applies, when it is a project start. */
  goal?: ProjectGoalId;
  /** Where the scenario opens when it is not a project start (web path). */
  route?: string;
  /** Needs a LiDAR-equipped iPhone/iPad to be measured rather than estimated. */
  prefersLidar?: boolean;
  limits?: CaptureLimits;
  guide: GuideStep[];
}

export const SCENARIO_GROUPS: readonly { id: ScenarioGroup; title: Bilingual; note: Bilingual }[] = [
  { id: "scan", title: { ru: "Сканировать", en: "Scan" }, note: { ru: "Камера телефона или LiDAR", en: "Phone camera or LiDAR" } },
  { id: "generate", title: { ru: "Создать с AI", en: "Create with AI" }, note: { ru: "Из описания или фото", en: "From a description or photo" } },
  { id: "model", title: { ru: "Моделировать", en: "Model" }, note: { ru: "Точные размеры и CAD", en: "Exact dimensions and CAD" } },
  { id: "bring", title: { ru: "Принести своё", en: "Bring your own" }, note: { ru: "Файлы и планы", en: "Files and plans" } },
];

const PREPARE_LIGHT: Bilingual = {
  ru: "Ровный яркий свет без резких теней.",
  en: "Bright, even light without harsh shadows.",
};

export const CREATE_SCENARIOS: readonly CreateScenario[] = [
  {
    id: "room_scan",
    group: "scan",
    icon: "▱",
    title: { ru: "Комната", en: "Room" },
    note: { ru: "Стены, проёмы и площадь; можно добавить мебель.", en: "Walls, openings and area; furniture optional." },
    goal: "room_scan",
    prefersLidar: true,
    guide: [
      {
        title: { ru: "Подготовьте помещение", en: "Prepare the space" },
        tips: [
          { ru: "Включите свет и откройте двери.", en: "Turn on the lights and open the doors." },
          { ru: "Уберите людей, животных и то, что мешает видеть стены.", en: "Clear people, pets and anything hiding the walls." },
        ],
      },
      {
        title: { ru: "Снимайте по стенам", en: "Scan along the walls" },
        tips: [
          { ru: "Начните с нижнего края стены и ведите вдоль неё.", en: "Start at the bottom edge of a wall and follow it." },
          { ru: "Следите за площадью на экране: она растёт по мере съёмки.", en: "Watch the area on screen grow as you scan." },
          { ru: "Не торопитесь в углах и проёмах.", en: "Slow down at corners and openings." },
        ],
      },
      {
        title: { ru: "Проверьте и продолжите", en: "Review and continue" },
        tips: [
          { ru: "Когда комната готова, можно снять следующую и объединить их.", en: "When the room is done, scan the next one and merge them." },
        ],
      },
    ],
  },
  {
    id: "interior_structure",
    group: "scan",
    icon: "⌂",
    title: { ru: "Дом изнутри", en: "Home interior" },
    note: { ru: "Несколько комнат, собранных в один план.", en: "Several rooms merged into one plan." },
    goal: "interior_structure",
    prefersLidar: true,
    guide: [
      {
        title: { ru: "Подготовьте дом", en: "Prepare the home" },
        tips: [
          { ru: "Откройте все двери между комнатами.", en: "Open every door between rooms." },
          { ru: "Начинайте с комнаты, откуда удобно выйти в соседние.", en: "Start in a room that connects to the others." },
        ],
      },
      {
        title: { ru: "Снимайте комнату за комнатой", en: "Scan room by room" },
        tips: [
          { ru: "После каждой комнаты выберите «Продолжить» и перейдите в следующую.", en: "After each room choose Continue and move to the next." },
          { ru: "Захватывайте проём между комнатами с обеих сторон.", en: "Capture each doorway from both sides." },
        ],
      },
      {
        title: { ru: "Соберите план", en: "Assemble the plan" },
        tips: [{ ru: "Выберите комнаты, которые нужно показать, и получите общий план этажа.", en: "Pick the rooms to show and get one floor plan." }],
      },
    ],
  },
  {
    id: "exterior_structure",
    group: "scan",
    icon: "▰",
    title: { ru: "Здание снаружи", en: "Building exterior" },
    note: { ru: "Фасады отдельными проходами и видимая часть крыши.", en: "Facade passes and the visible roof." },
    goal: "exterior_structure",
    limits: { minFrames: 32, maxFrames: 150 },
    guide: [
      {
        title: { ru: "Выберите время и точку", en: "Pick the time and place" },
        tips: [
          PREPARE_LIGHT,
          { ru: "Снимайте с земли или разрешённой площадки: не поднимайтесь ради кадра.", en: "Shoot from the ground or a permitted spot; never climb for a shot." },
        ],
      },
      {
        title: { ru: "Обойдите здание по кругу", en: "Walk around the building" },
        tips: [
          { ru: "Четыре фасада по очереди, кадры внахлёст.", en: "Four facades in turn, frames overlapping." },
          { ru: "Захватывайте угол предыдущей стены, чтобы замкнуть обход.", en: "Include the corner of the previous wall to close the loop." },
        ],
      },
      {
        title: { ru: "Укажите размер", en: "Give one real size" },
        tips: [{ ru: "Измерьте одну известную длину, чтобы результат был в миллиметрах.", en: "Measure one known length so the result is in millimetres." }],
      },
    ],
  },
  {
    id: "object_scan",
    group: "scan",
    icon: "◈",
    title: { ru: "Предмет", en: "Object" },
    note: { ru: "Обход по кругу, фотограмметрия.", en: "Walk around it; photogrammetry." },
    goal: "object_scan",
    limits: { minFrames: 12, maxFrames: 150 },
    guide: [
      {
        title: { ru: "Подготовьте предмет", en: "Prepare the object" },
        tips: [
          { ru: "Выберите предмет с множеством деталей; гладкий и блестящий снимается хуже.", en: "Pick an object with plenty of detail; smooth or shiny ones scan worse." },
          { ru: "Поставьте его на возвышение, чтобы обойти со всех сторон.", en: "Raise it on a stool so you can circle it." },
          PREPARE_LIGHT,
        ],
      },
      {
        title: { ru: "Снимайте кольцами", en: "Capture in rings" },
        tips: [
          { ru: "Обходите предмет по кругу на разной высоте.", en: "Circle the object at several heights." },
          { ru: "Покройте все углы и не двигайте предмет во время съёмки.", en: "Cover every angle and do not move the object while shooting." },
          { ru: "Нужно минимум 12 кадров; для хорошего результата снимите 20 и больше.", en: "At least 12 frames are needed; shoot 20 or more for a good result." },
        ],
      },
      {
        title: { ru: "Выберите обработку", en: "Choose processing" },
        tips: [{ ru: "Для печати подходит фотограмметрия; для бликов и мелких деталей — гауссовы сплаты.", en: "Photogrammetry suits printing; Gaussian splats suit reflections and fine detail." }],
      },
    ],
  },
  {
    id: "printable_object",
    group: "generate",
    icon: "▣",
    title: { ru: "Модель для печати", en: "Printable model" },
    note: { ru: "Проверка печатаемости, 3MF и слайсер.", en: "Print checks, 3MF and slicing." },
    goal: "printable_object",
    guide: [],
  },
  {
    id: "general_character",
    group: "generate",
    icon: "♙",
    title: { ru: "Персонаж", en: "Character" },
    note: { ru: "Органическая форма, поза и материалы.", en: "Organic form, pose and materials." },
    goal: "general_character",
    guide: [],
  },
  {
    id: "game_character",
    group: "generate",
    icon: "♞",
    title: { ru: "Персонаж для игры", en: "Game character" },
    note: { ru: "LOD, игровой GLB и коллайдер.", en: "LODs, game-ready GLB and collider." },
    goal: "game_character",
    guide: [],
  },
  {
    id: "game_environment",
    group: "generate",
    icon: "▤",
    title: { ru: "Карта / окружение", en: "Map / environment" },
    note: { ru: "Крупный масштаб, сцена и игровой экспорт.", en: "Large scale, scene and game export." },
    goal: "game_environment",
    guide: [],
  },
  {
    id: "house_design",
    group: "model",
    icon: "⌂",
    title: { ru: "Создать дизайн дома", en: "Create a house design" },
    note: { ru: "Быстрый старт: форма, размеры и этажи.", en: "Quick start: shape, dimensions and floors." },
    goal: "house_design",
    guide: [],
  },
  {
    id: "machine_part",
    group: "model",
    icon: "⚙",
    title: { ru: "Деталь / техника", en: "Part / machine" },
    note: { ru: "Точные размеры, CAD-инструменты и STEP.", en: "Exact dimensions, CAD tools and STEP." },
    goal: "machine_part",
    guide: [],
  },
  {
    id: "dimensioned_part",
    group: "model",
    icon: "⌑",
    title: { ru: "Деталь по чертежу", en: "Part from a drawing" },
    note: { ru: "Фото чертежа, калибровка и CAD.", en: "Drawing photo, calibration and CAD." },
    goal: "dimensioned_part",
    guide: [],
  },
  {
    id: "floor_plan",
    group: "bring",
    icon: "▦",
    title: { ru: "План этажа", en: "Floor plan" },
    note: { ru: "Размеры комнаты или подложка, разметка пинами и облаками.", en: "Room size or an underlay; mark up with pins and clouds." },
    route: "/plan",
    guide: [],
  },
  {
    id: "import_file",
    group: "bring",
    icon: "⇩",
    title: { ru: "3D-файл", en: "3D file" },
    note: { ru: "Загрузите STL, OBJ, GLB, FBX, STEP и другие.", en: "Upload STL, OBJ, GLB, FBX, STEP and more." },
    route: "/convert",
    guide: [],
  },
];

export function getScenario(id: string | null | undefined): CreateScenario | null {
  return CREATE_SCENARIOS.find((scenario) => scenario.id === id) ?? null;
}

export function scenariosIn(group: ScenarioGroup): CreateScenario[] {
  return CREATE_SCENARIOS.filter((scenario) => scenario.group === group);
}

/** Where a scenario sends the person on the web (the same path the desktop shell opens). */
export function scenarioPath(scenario: CreateScenario, goalScanSubject?: string): string {
  if (scenario.route) return scenario.route;
  if (scenario.goal && goalScanSubject) return `/scanner?source=phone&subject=${goalScanSubject}`;
  return `/new?scenario=${scenario.id}`;
}

// --- capture progress --------------------------------------------------------------------

export type FrameState = "empty" | "too_few" | "ready" | "full";

export interface FrameProgress {
  state: FrameState;
  count: number;
  /** 0..1 along the min..max scale, for a progress bar with a minimum tick. */
  fraction: number;
  /** Where the minimum sits on that same bar, 0..1. */
  minimumMark: number;
  remainingToMinimum: number;
  canProcess: boolean;
}

export function frameProgress(count: number, limits: CaptureLimits): FrameProgress {
  const shots = Math.max(0, Math.floor(count));
  const state: FrameState =
    shots === 0 ? "empty" : shots < limits.minFrames ? "too_few" : shots >= limits.maxFrames ? "full" : "ready";
  return {
    state,
    count: shots,
    fraction: Math.min(shots / limits.maxFrames, 1),
    minimumMark: limits.minFrames / limits.maxFrames,
    remainingToMinimum: Math.max(limits.minFrames - shots, 0),
    canProcess: shots >= limits.minFrames,
  };
}

export function frameMessage(progress: FrameProgress, limits: CaptureLimits, language: "ru" | "en"): string {
  const ru = language === "ru";
  switch (progress.state) {
    case "empty":
      return ru ? `Нужно минимум ${limits.minFrames} кадров` : `At least ${limits.minFrames} frames are needed`;
    case "too_few":
      return ru ? `Ещё ${progress.remainingToMinimum} до минимума` : `${progress.remainingToMinimum} more to the minimum`;
    case "full":
      return ru ? "Достигнут максимум кадров" : "Maximum frames reached";
    default:
      return ru ? "Можно обрабатывать или снимать дальше" : "Ready to process, or keep shooting";
  }
}

// --- processing options -------------------------------------------------------------------

export type ScanMethod = "photogrammetry" | "gaussian_splat";
export type QualityId = "fast" | "default" | "dense" | "raw";

export interface QualityPreset {
  id: QualityId;
  title: Bilingual;
  /** What it is good for, shown under the selector. */
  use: Bilingual;
  /** Rough share of the heaviest option's triangles. */
  weight: number;
  /** Needs a paid plan in products that gate it; informational only here. */
  heavy: boolean;
}

export const QUALITY_PRESETS: readonly QualityPreset[] = [
  { id: "fast", title: { ru: "Быстро", en: "Fast" }, use: { ru: "Быстрый просмотр и проверка снимков. Меньше деталей.", en: "A quick look to check the shots. Less detail." }, weight: 0.1, heavy: false },
  { id: "default", title: { ru: "По умолчанию", en: "Default" }, use: { ru: "Хороший баланс детализации и удобства. Лучше всего для игр, мобильных устройств и печати.", en: "A good balance of detail and ease. Best for games, mobile and printing." }, weight: 0.3, heavy: false },
  { id: "dense", title: { ru: "Плотно", en: "Dense" }, use: { ru: "Богатая детализация. Для анимации, AR/VR и подробных рендеров.", en: "Rich detail for animation, AR/VR and detailed renders." }, weight: 0.7, heavy: true },
  { id: "raw", title: { ru: "Сырой", en: "Raw" }, use: { ru: "Без упрощения: максимум геометрии для дальнейшей обработки в других программах.", en: "No simplification: maximum geometry for further work elsewhere." }, weight: 1, heavy: true },
];

export const TEXTURE_SIZES = [1024, 2048, 4096, 8192] as const;
export type TextureSize = (typeof TEXTURE_SIZES)[number];

export interface ExportFormatInfo {
  id: string;
  title: string;
  best: Bilingual;
  /** Carries colour/texture. */
  textured: boolean;
}

export const EXPORT_FORMATS: readonly ExportFormatInfo[] = [
  { id: "glb", title: "GLB", best: { ru: "Веб, игры и AR; одним файлом с текстурами.", en: "Web, games and AR; one file with textures." }, textured: true },
  { id: "3mf", title: "3MF", best: { ru: "3D-печать: размеры и материалы.", en: "3D printing: units and materials." }, textured: false },
  { id: "stl", title: "STL", best: { ru: "Любой слайсер; без цвета.", en: "Any slicer; no colour." }, textured: false },
  { id: "obj", title: "OBJ", best: { ru: "Универсальный обмен с графическими программами.", en: "Universal exchange with graphics tools." }, textured: true },
  { id: "fbx", title: "FBX", best: { ru: "Unity, Unreal и анимация.", en: "Unity, Unreal and animation." }, textured: true },
  { id: "usdz", title: "USDZ", best: { ru: "Просмотр на iPhone и iPad (AR Quick Look).", en: "Viewing on iPhone and iPad (AR Quick Look)." }, textured: true },
  { id: "ply", title: "PLY", best: { ru: "Цвет по вершинам и облака точек.", en: "Per-vertex colour and point clouds." }, textured: true },
  { id: "step", title: "STEP", best: { ru: "CAD: точные тела, не сетка.", en: "CAD: exact solids, not a mesh." }, textured: false },
];

export interface ProcessingOptions {
  method: ScanMethod;
  quality: QualityId;
  texture: TextureSize;
  format: string;
  /** Cut the object out of its surroundings (needed when the object was turned over). */
  maskObject: boolean;
  /** Let the platform learn from this upload. Off until the person turns it on. */
  allowTraining: boolean;
  /** Let others find this model. Off until the person turns it on. */
  publicVisibility: boolean;
}

export function defaultProcessing(): ProcessingOptions {
  return {
    method: "photogrammetry",
    quality: "default",
    texture: 2048,
    format: "glb",
    maskObject: false,
    allowTraining: false,
    publicVisibility: false,
  };
}

/** Reads stored or received options back, falling back to the defaults for anything invalid. */
export function normalizeProcessing(value: unknown): ProcessingOptions {
  const base = defaultProcessing();
  if (!value || typeof value !== "object") return base;
  const raw = value as Record<string, unknown>;
  return {
    method: raw.method === "gaussian_splat" ? "gaussian_splat" : "photogrammetry",
    quality: QUALITY_PRESETS.some((q) => q.id === raw.quality) ? (raw.quality as QualityId) : base.quality,
    texture: TEXTURE_SIZES.includes(raw.texture as TextureSize) ? (raw.texture as TextureSize) : base.texture,
    format: EXPORT_FORMATS.some((f) => f.id === raw.format) ? (raw.format as string) : base.format,
    maskObject: raw.maskObject === true,
    allowTraining: raw.allowTraining === true,
    publicVisibility: raw.publicVisibility === true,
  };
}

/** What each method is good at, for the comparison table shown before processing. */
export const METHOD_COMPARISON: readonly { feature: Bilingual; photogrammetry: boolean; gaussian_splat: boolean }[] = [
  { feature: { ru: "Текстурные поверхности", en: "Textured surfaces" }, photogrammetry: true, gaussian_splat: true },
  { feature: { ru: "Органические объекты", en: "Organic objects" }, photogrammetry: true, gaussian_splat: true },
  { feature: { ru: "Блестящие поверхности", en: "Reflective surfaces" }, photogrammetry: false, gaussian_splat: true },
  { feature: { ru: "Прозрачность", en: "Transparency" }, photogrammetry: false, gaussian_splat: true },
  { feature: { ru: "Мелкие детали", en: "Fine details" }, photogrammetry: false, gaussian_splat: true },
  { feature: { ru: "Экспорт для 3D-печати", en: "3D print export" }, photogrammetry: true, gaussian_splat: false },
  { feature: { ru: "Экспорт облака точек", en: "Point cloud export" }, photogrammetry: false, gaussian_splat: true },
];

/** Which method fits what the person said they want, so the choice starts sensibly. */
export function suggestMethod(needs: { printing?: boolean; shiny?: boolean; fineDetail?: boolean }): ScanMethod {
  if (needs.printing) return "photogrammetry";
  return needs.shiny || needs.fineDetail ? "gaussian_splat" : "photogrammetry";
}

/** A rough size of the result in MB, so the person sees the cost of a setting before choosing it. */
export function estimateResultMb(frames: number, quality: QualityId, texture: TextureSize): number {
  const preset = QUALITY_PRESETS.find((q) => q.id === quality) ?? (QUALITY_PRESETS[1] as QualityPreset);
  const geometry = Math.max(frames, 1) * 0.12 * (0.2 + preset.weight);
  const textureMb = (texture / 1024) ** 2 * 0.9;
  return Math.round((geometry + textureMb) * 10) / 10;
}

// --- game export density -----------------------------------------------------------------

export interface GameBudget {
  id: "low" | "medium" | "high" | "ultra";
  title: Bilingual;
  /** Triangles in LOD0 (the export's `max_triangles`). */
  triangles: number;
  use: Bilingual;
}

/** The density choices for a game asset, in words; each maps to the export's triangle budget. */
export const GAME_BUDGETS: readonly GameBudget[] = [
  { id: "low", title: { ru: "Низкий", en: "Low" }, triangles: 5_000, use: { ru: "Мобильные игры, веб и далёкие объекты.", en: "Mobile games, web and distant objects." } },
  { id: "medium", title: { ru: "Средний", en: "Medium" }, triangles: 20_000, use: { ru: "Основной выбор для ПК и консолей: баланс деталей и скорости.", en: "The usual choice for PC and console: detail balanced with speed." } },
  { id: "high", title: { ru: "Высокий", en: "High" }, triangles: 50_000, use: { ru: "Герои, анимация, AR/VR и крупные планы.", en: "Heroes, animation, AR/VR and close-ups." } },
  { id: "ultra", title: { ru: "Ультра", en: "Ultra" }, triangles: 100_000, use: { ru: "Детальные рендеры и окружения; тяжёлый файл.", en: "Detailed renders and environments; a heavy file." } },
];

/** The preset whose budget is closest to a given triangle count. */
export function nearestGameBudget(triangles: number): GameBudget {
  let best = GAME_BUDGETS[0] as GameBudget;
  for (const item of GAME_BUDGETS) {
    if (Math.abs(item.triangles - triangles) < Math.abs(best.triangles - triangles)) best = item;
  }
  return best;
}

/** Formats the export endpoint can write today, with the plain-language "best for" line. */
export const EXPORTABLE_FORMATS: readonly ExportFormatInfo[] = [
  ...EXPORT_FORMATS.filter((format) => ["stl", "3mf", "glb", "fbx", "step"].includes(format.id)),
  { id: "iges", title: "IGES", best: { ru: "CAD: старый обменный формат точных тел.", en: "CAD: the older exchange format for exact solids." }, textured: false },
];
