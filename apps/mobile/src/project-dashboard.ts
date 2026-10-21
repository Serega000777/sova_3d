export type ProjectCheckState = "not_run" | "passed" | "warning" | "failed";

export interface ProjectDashboardState {
  modelLabel: string;
  checkLabel: string;
  versionLabel: string;
}

export function projectDashboardState(input: {
  hasModel: boolean;
  versionCount: number;
  checkState: ProjectCheckState;
}): ProjectDashboardState {
  const checkLabel = {
    not_run: "Проверка не запускалась",
    passed: "Проверка пройдена",
    warning: "Есть замечания проверки",
    failed: "Проверка не пройдена",
  }[input.checkState];
  const versions = Math.max(0, Math.trunc(input.versionCount));
  return {
    modelLabel: input.hasModel ? "Модель создана" : "Черновик без модели",
    checkLabel,
    versionLabel: `${versions} ${versions === 1 ? "версия" : versions >= 2 && versions <= 4 ? "версии" : "версий"}`,
  };
}
