export type ProjectCheckState = "not_run" | "passed" | "warning" | "failed";

export interface ProjectDashboardState {
  modelLabel: string;
  checkLabel: string;
  versionLabel: string;
  participantLabel: string | null;
}

function countLabel(value: number, one: string, few: string, many: string): string {
  const lastTwo = value % 100;
  const last = value % 10;
  const noun = lastTwo >= 11 && lastTwo <= 14
    ? many
    : last === 1
      ? one
      : last >= 2 && last <= 4
        ? few
        : many;
  return `${value} ${noun}`;
}

export function projectDashboardState(input: {
  hasModel: boolean;
  versionCount: number;
  checkState: ProjectCheckState;
  participantCount: number | null;
}): ProjectDashboardState {
  const checkLabel = {
    not_run: "Проверка не запускалась",
    passed: "Проверка пройдена",
    warning: "Есть замечания проверки",
    failed: "Проверка не пройдена",
  }[input.checkState];
  const versions = Math.max(0, Math.trunc(input.versionCount));
  const participants = input.participantCount === null
    ? null
    : Math.max(1, Math.trunc(input.participantCount));
  return {
    modelLabel: input.hasModel ? "Модель создана" : "Черновик без модели",
    checkLabel,
    versionLabel: countLabel(versions, "версия", "версии", "версий"),
    participantLabel: participants === null
      ? null
      : countLabel(participants, "участник", "участника", "участников"),
  };
}
