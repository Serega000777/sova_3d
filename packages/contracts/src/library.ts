/** The project library: search, sort and filter the same way on every client. */

export interface LibraryItem {
  id: string;
  name: string;
  description?: string | null;
  head_version_id?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export type LibrarySort = "updated" | "created" | "name";
export type LibraryFilter = "all" | "models" | "drafts";

export interface LibraryQuery {
  query?: string;
  sort?: LibrarySort;
  filter?: LibraryFilter;
}

/** A project with no version yet is a draft: created, but nothing built or scanned in it. */
export function isDraft(item: LibraryItem): boolean {
  return !item.head_version_id;
}

function stamp(value: string | null | undefined): number {
  const time = value ? Date.parse(value) : Number.NaN;
  return Number.isFinite(time) ? time : 0;
}

/** Case-insensitive match on the name and description; every word must appear. */
export function matchesQuery(item: LibraryItem, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = `${item.name} ${item.description ?? ""}`.toLowerCase();
  return words.every((word) => haystack.includes(word));
}

export function libraryView<T extends LibraryItem>(items: readonly T[], options: LibraryQuery = {}): T[] {
  const { query = "", sort = "updated", filter = "all" } = options;
  const kept = items.filter((item) => {
    if (filter === "models" && isDraft(item)) return false;
    if (filter === "drafts" && !isDraft(item)) return false;
    return matchesQuery(item, query);
  });
  const by: Record<LibrarySort, (a: T, b: T) => number> = {
    updated: (a, b) => stamp(b.updated_at ?? b.created_at) - stamp(a.updated_at ?? a.created_at),
    created: (a, b) => stamp(b.created_at) - stamp(a.created_at),
    name: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base", numeric: true }),
  };
  return [...kept].sort(by[sort]);
}

/** "5 мин назад" / "5 min ago" style, falling back to the date for anything older than a week. */
export function relativeTime(iso: string, now: number, language: "ru" | "en"): string {
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "";
  const minutes = Math.max(Math.round((now - then) / 60_000), 0);
  const ru = language === "ru";
  if (minutes < 1) return ru ? "только что" : "just now";
  if (minutes < 60) return ru ? `${minutes} мин назад` : `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return ru ? `${hours} ч назад` : `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return ru ? `${days} дн. назад` : `${days} d ago`;
  return new Date(then).toLocaleDateString(ru ? "ru-RU" : "en-GB");
}
