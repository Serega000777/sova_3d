/**
 * Account-tier UI gate (F-account-tier): which studio tools and which "detail" operation
 * kinds belong to the paid Pro toolset. The API independently enforces the same boundary;
 * this module makes the client honest and keeps paid features visible for discovery.
 */
export type DetailKind = "hole" | "fillet" | "chamfer" | "shell" | "pattern" | "circle" | "mirror";

/** Whole tool-rail panels that are Pro-only; everything else stays free. */
export const PRO_LOCKED_TOOLS: readonly string[] = ["reverse", "engineer", "fit", "parts"];

/** "Detail" operation kinds that are Pro-only; "hole" is the one that stays on the Free plan. */
export const PRO_LOCKED_DETAILS: readonly DetailKind[] = [
  "fillet",
  "chamfer",
  "shell",
  "pattern",
  "circle",
  "mirror",
];

export const TIER_FEATURES = {
  free: {
    ru: [
      "Создание через ИИ, фото и одиночные сканы",
      "Базовые формы, перемещение, размеры и отверстия",
      "Проверка и подготовка к 3D-печати",
      "Экспорт STL, 3MF, GLB и FBX",
      "Линейная история версий",
    ],
    en: [
      "AI, photo and single-scan creation",
      "Basic shapes, transforms, dimensions and holes",
      "3D-print checks and preparation",
      "STL, 3MF, GLB and FBX export",
      "Linear version history",
    ],
  },
  pro: {
    ru: [
      "Всё из Free",
      "Boolean, fillet, chamfer, shell, pattern и mirror",
      "Редактирование mesh и топологии",
      "В CAD, Инженер, Посадка и разрезание на части",
      "STEP/IGES и game-ready экспорт с LOD, UV и коллайдером",
      "Откат и сравнение сохранённых версий",
    ],
    en: [
      "Everything in Free",
      "Boolean, fillet, chamfer, shell, pattern and mirror",
      "Mesh and topology editing",
      "To CAD, Engineer, Fit and split into parts",
      "STEP/IGES and game-ready export with LODs, UVs and a collider",
      "Rollback and comparison of saved versions",
    ],
  },
} as const;

export function isProTierLockedTool(toolId: string, detail?: string): boolean {
  if (PRO_LOCKED_TOOLS.includes(toolId)) return true;
  if (toolId === "detail" && detail) return PRO_LOCKED_DETAILS.includes(detail as DetailKind);
  return false;
}
