import type { Project } from "@physical-ai/contracts";

export interface ProjectActivityDay {
  day: string;
  updatedProjects: number;
}

export interface ProjectAnalytics {
  totalProjects: number;
  modelsCreated: number;
  drafts: number;
  updatedInWindow: number;
  activity: ProjectActivityDay[];
  mostRecent: Project | null;
}

const DAY_MS = 24 * 60 * 60 * 1000;

function utcDay(timestamp: number): number {
  const date = new Date(timestamp);
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
}

function projectTimestamp(project: Project): number | null {
  const timestamp = Date.parse(project.updated_at ?? project.created_at);
  return Number.isFinite(timestamp) ? timestamp : null;
}

/**
 * Builds only statistics supported by the canonical project list. In particular, this does not
 * infer project completion or aggregate integrity-check percentages: neither is present in
 * ProjectOut today.
 */
export function buildProjectAnalytics(
  projects: Project[],
  nowMs: number,
  windowDays = 30,
): ProjectAnalytics {
  const days = Math.max(1, Math.trunc(windowDays));
  const today = utcDay(nowMs);
  const firstDay = today - (days - 1) * DAY_MS;
  const activity = Array.from({ length: days }, (_, index) => ({
    day: new Date(firstDay + index * DAY_MS).toISOString().slice(0, 10),
    updatedProjects: 0,
  }));
  const activityByDay = new Map(activity.map((item) => [item.day, item]));
  let updatedInWindow = 0;
  let mostRecent: Project | null = null;
  let mostRecentTimestamp = Number.NEGATIVE_INFINITY;

  for (const project of projects) {
    const timestamp = projectTimestamp(project);
    if (timestamp === null) continue;
    if (timestamp <= nowMs && timestamp > mostRecentTimestamp) {
      mostRecentTimestamp = timestamp;
      mostRecent = project;
    }
    const projectDay = utcDay(timestamp);
    if (projectDay < firstDay || projectDay > today) continue;
    updatedInWindow += 1;
    const bucket = activityByDay.get(new Date(projectDay).toISOString().slice(0, 10));
    if (bucket) bucket.updatedProjects += 1;
  }

  const modelsCreated = projects.filter((project) => project.head_version_id !== null).length;
  return {
    totalProjects: projects.length,
    modelsCreated,
    drafts: projects.length - modelsCreated,
    updatedInWindow,
    activity,
    mostRecent,
  };
}
