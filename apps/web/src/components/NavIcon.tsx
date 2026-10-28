import type { ReactNode, SVGProps } from "react";

export type NavIconName =
  | "modeling"
  | "projects"
  | "convert"
  | "slicer"
  | "market"
  | "scanner"
  | "plans"
  | "plus"
  | "chevron"
  | "menu"
  | "close";

const paths: Record<NavIconName, ReactNode> = {
  modeling: <><path d="m12 2.75 7.75 4.4v8.7L12 20.25l-7.75-4.4v-8.7L12 2.75Z"/><path d="m4.45 7.3 7.55 4.35 7.55-4.35M12 11.65v8.35"/></>,
  projects: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
  convert: <><path d="M4 7h13"/><path d="m14 4 3 3-3 3M20 17H7"/><path d="m10 14-3 3 3 3"/></>,
  slicer: <><path d="m4 7 8-4 8 4-8 4-8-4Z"/><path d="m4 12 8 4 8-4M4 17l8 4 8-4"/></>,
  market: <><path d="M4 9.5h16l-1.2 10H5.2L4 9.5Z"/><path d="M7 9.5 8.5 4h7L17 9.5M9 13v3M15 13v3"/></>,
  scanner: <><path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/><path d="M8 9.5 12 7l4 2.5v5L12 17l-4-2.5v-5Z"/></>,
  plans: <><path d="M4 4h6v6H4V4ZM14 4h6v10h-6V4ZM4 14h6v6H4v-6ZM14 18h6"/></>,
  plus: <path d="M12 5v14M5 12h14"/>,
  chevron: <path d="m8 10 4 4 4-4"/>,
  menu: <><path d="M4 7h16M4 12h16M4 17h16"/></>,
  close: <><path d="m6 6 12 12M18 6 6 18"/></>,
};

export function NavIcon({ name, ...props }: { name: NavIconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {paths[name]}
    </svg>
  );
}
