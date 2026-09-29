/**
 * F-084 / T-231: the same project-start choices on web, desktop and mobile.
 *
 * These are workflow defaults, not permanent project types.  A project remains an
 * ordinary project after creation and every editor/export tool stays available.
 */
export type ProjectGoalId =
  | "printable_object"
  | "general_character"
  | "game_character"
  | "game_environment"
  | "machine_part"
  | "dimensioned_part"
  | "object_scan"
  | "room_scan"
  | "interior_structure"
  | "exterior_structure";

export type ProjectGoalSource = "description" | "photo" | "scan";
export type ProjectGoalTarget = "print" | "game" | "cad";
export type ProjectGoalScanSubject = "object" | "room" | "home" | "exterior";

export interface ProjectGoal {
  id: ProjectGoalId;
  icon: string;
  title: { ru: string; en: string };
  note: { ru: string; en: string };
  defaultName: { ru: string; en: string };
  defaultPrompt: { ru: string; en: string };
  source: ProjectGoalSource;
  workflow: "variants" | "organic" | "photo" | "scan";
  target: ProjectGoalTarget;
  format: "3mf" | "glb" | "step";
  scanSubject?: ProjectGoalScanSubject;
  studioMode: "simple" | "pro";
}

export const PROJECT_GOALS: readonly ProjectGoal[] = [
  {
    id: "printable_object",
    icon: "▣",
    title: { ru: "Модель для печати", en: "Printable object" },
    note: { ru: "Проверка печатаемости, 3MF и слайсер.", en: "Print checks, 3MF and slicing." },
    defaultName: { ru: "Новый объект для печати", en: "New printable object" },
    defaultPrompt: { ru: "", en: "" },
    source: "description",
    workflow: "variants",
    target: "print",
    format: "3mf",
    studioMode: "simple",
  },
  {
    id: "general_character",
    icon: "♙",
    title: { ru: "Персонаж", en: "Character" },
    note: { ru: "Органическая форма, поза и материалы.", en: "Organic form, pose and materials." },
    defaultName: { ru: "Новый персонаж", en: "New character" },
    defaultPrompt: { ru: "Персонаж: ", en: "Character: " },
    source: "description",
    workflow: "organic",
    target: "game",
    format: "glb",
    studioMode: "simple",
  },
  {
    id: "game_character",
    icon: "♞",
    title: { ru: "Персонаж для игры", en: "Game character" },
    note: { ru: "LOD, игровой GLB и коллайдер.", en: "LODs, game-ready GLB and collider." },
    defaultName: { ru: "Игровой персонаж", en: "Game character" },
    defaultPrompt: { ru: "Игровой персонаж: ", en: "Game character: " },
    source: "description",
    workflow: "organic",
    target: "game",
    format: "glb",
    studioMode: "pro",
  },
  {
    id: "game_environment",
    icon: "▤",
    title: { ru: "Карта / окружение", en: "Game map / environment" },
    note: { ru: "Крупный масштаб, сцена, LOD и игровой экспорт.", en: "Large scale, scene tools, LODs and game export." },
    defaultName: { ru: "Игровое окружение", en: "Game environment" },
    defaultPrompt: { ru: "Игровое окружение: ", en: "Game environment: " },
    source: "description",
    workflow: "variants",
    target: "game",
    format: "glb",
    studioMode: "pro",
  },
  {
    id: "machine_part",
    icon: "⚙",
    title: { ru: "Машина / техника / деталь", en: "Machine / technical part" },
    note: { ru: "Точные размеры, CAD-инструменты и STEP.", en: "Exact dimensions, CAD tools and STEP." },
    defaultName: { ru: "Новая техническая деталь", en: "New technical part" },
    defaultPrompt: { ru: "Деталь с точными размерами: ", en: "Dimensioned technical part: " },
    source: "description",
    workflow: "variants",
    target: "cad",
    format: "step",
    studioMode: "pro",
  },
  {
    id: "dimensioned_part",
    icon: "⌑",
    title: { ru: "Деталь по чертежу", en: "Part from a drawing" },
    note: { ru: "Фото чертежа, калибровка размеров и CAD.", en: "Drawing reference, dimensional calibration and CAD." },
    defaultName: { ru: "Деталь по чертежу", en: "Part from drawing" },
    defaultPrompt: { ru: "Построй деталь по чертежу и указанным размерам.", en: "Build the part from the drawing and its dimensions." },
    source: "photo",
    workflow: "photo",
    target: "cad",
    format: "step",
    studioMode: "pro",
  },
  {
    id: "object_scan",
    icon: "◈",
    title: { ru: "Скан предмета", en: "Object scan" },
    note: { ru: "Обход предмета по кругу и фотограмметрия.", en: "Walk around an object for photogrammetry." },
    defaultName: { ru: "Скан предмета", en: "Object scan" },
    defaultPrompt: { ru: "", en: "" },
    source: "scan",
    workflow: "scan",
    target: "print",
    format: "3mf",
    scanSubject: "object",
    studioMode: "simple",
  },
  {
    id: "room_scan",
    icon: "▱",
    title: { ru: "Скан комнаты", en: "Room scan" },
    note: { ru: "Одна комната: RoomPlan с LiDAR или фотокадры.", en: "One room with LiDAR RoomPlan or photos." },
    defaultName: { ru: "Скан комнаты", en: "Room scan" },
    defaultPrompt: { ru: "", en: "" },
    source: "scan",
    workflow: "scan",
    target: "cad",
    format: "glb",
    scanSubject: "room",
    studioMode: "simple",
  },
  {
    id: "interior_structure",
    icon: "⌂",
    title: { ru: "Дом / здание изнутри", en: "Complete interior structure" },
    note: { ru: "Несколько комнат как секции одного объекта.", en: "Multiple rooms as sections of one structure." },
    defaultName: { ru: "Интерьер дома", en: "Interior structure" },
    defaultPrompt: { ru: "", en: "" },
    source: "scan",
    workflow: "scan",
    target: "cad",
    format: "glb",
    scanSubject: "home",
    studioMode: "pro",
  },
  {
    id: "exterior_structure",
    icon: "▰",
    title: { ru: "Здание снаружи", en: "Exterior building scan" },
    note: { ru: "Фасады и видимые части крыши отдельными проходами.", en: "Facade passes and safely visible roof areas." },
    defaultName: { ru: "Наружный скан здания", en: "Exterior building scan" },
    defaultPrompt: { ru: "", en: "" },
    source: "scan",
    workflow: "scan",
    target: "cad",
    format: "glb",
    scanSubject: "exterior",
    studioMode: "pro",
  },
];

export function getProjectGoal(value: string | null | undefined): ProjectGoal | null {
  return PROJECT_GOALS.find((goal) => goal.id === value) ?? null;
}
