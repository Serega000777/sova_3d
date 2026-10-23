import type { IntegrityReport } from "@physical-ai/contracts";

function value(value: number | string | boolean | null): string {
  if (value === null) return "—";
  return typeof value === "boolean" ? (value ? "true" : "false") : String(value);
}

export function integrityReportText({
  report,
  projectName,
  projectId,
  versionId,
  sequenceNo,
  language,
}: {
  report: IntegrityReport;
  projectName: string;
  projectId: string;
  versionId: string;
  sequenceNo: number;
  language: "ru" | "en";
}): string {
  const ru = language === "ru";
  const dimensions = report.output.bboxSizeMm
    ? `${report.output.bboxSizeMm.map((item) => Math.round(item * 100) / 100).join(" × ")} ${ru ? "мм" : "mm"}`
    : "—";
  const checks = report.checks.map((check) =>
    `${check.status === "pass" ? "✓" : check.status === "warn" ? "?" : "!"} ${check.message} (${ru ? "ожидалось" : "expected"}: ${value(check.expected)}; ${ru ? "получено" : "actual"}: ${value(check.actual)})`,
  );
  return [
    ru ? "Отчёт о целостности Sova 3D" : "Sova 3D integrity report",
    `${ru ? "Проект" : "Project"}: ${projectName} (${projectId})`,
    `${ru ? "Версия" : "Version"}: v${sequenceNo} (${versionId})`,
    `${ru ? "Результат" : "Result"}: ${report.status.toUpperCase()}`,
    `${ru ? "Преобразование" : "Conversion"}: ${report.sourceFormat.toUpperCase()} → ${report.targetFormat.toUpperCase()}`,
    `${ru ? "Габариты" : "Dimensions"}: ${dimensions}`,
    `${ru ? "Грани" : "Faces"}: ${report.output.faces ?? "—"}`,
    `${ru ? "Вершины" : "Vertices"}: ${report.output.vertices ?? "—"}`,
    `${ru ? "Замкнута" : "Watertight"}: ${report.output.watertight === null ? "—" : report.output.watertight ? (ru ? "да" : "yes") : (ru ? "нет" : "no")}`,
    `${ru ? "Материалы" : "Materials"}: ${report.output.materialCount ?? "—"}`,
    `${ru ? "Текстуры" : "Textures"}: ${report.output.textureCount ?? "—"}`,
    `${ru ? "Узлы сцены" : "Scene nodes"}: ${report.output.nodeCount ?? "—"}`,
    `${ru ? "Mesh-объекты" : "Scene meshes"}: ${report.output.meshCount ?? "—"}`,
    `${ru ? "Анимации" : "Animations"}: ${report.output.animationCount ?? "—"}`,
    `${ru ? "Камеры" : "Cameras"}: ${report.output.cameraCount ?? "—"}`,
    `${ru ? "Источники света" : "Lights"}: ${report.output.lightCount ?? "—"}`,
    "",
    ru ? "Проверки:" : "Checks:",
    ...checks,
    "",
    `${ru ? "Итог" : "Summary"}: ${report.summary}`,
    ru
      ? "Отчёт проверяет преобразование файла; это не расчёт прочности и не сертификация."
      : "This report checks file conversion; it is not structural analysis or certification.",
  ].join("\n");
}
