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
  | "close"
  | "microphone"
  | "lock"
  | "fit"
  | "check"
  | "pin"
  | "hand"
  | "cloud"
  | "rectangle"
  | "circle"
  | "arrow"
  | "pencil"
  | "dimension"
  | "cursor"
  | "undo"
  | "redo"
  | "grid"
  | "feed"
  | "user"
  | "filters"
  | "cart"
  | "photo";

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
  microphone: <><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M9 21h6"/></>,
  lock: <><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/></>,
  fit: <><path d="M9 4H4v5M15 4h5v5M20 15v5h-5M9 20H4v-5"/><path d="m4 9 5-5M15 4l5 5M20 15l-5 5M9 20l-5-5"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  pin: <><path d="M12 21s6-5.2 6-11a6 6 0 1 0-12 0c0 5.8 6 11 6 11Z"/><circle cx="12" cy="10" r="2"/></>,
  hand: <path d="M7 11V7.5a1.5 1.5 0 0 1 3 0V10m0-4.5a1.5 1.5 0 0 1 3 0V10m0-3.5a1.5 1.5 0 0 1 3 0v4m0-2a1.5 1.5 0 0 1 3 0V14c0 4-2.5 7-7 7-3.2 0-5.1-1.5-6.5-4L3 12.8a1.5 1.5 0 0 1 2.4-1.7L7 12.5Z"/>,
  cloud: <path d="M5 17h13a4 4 0 0 0 .4-8A6.5 6.5 0 0 0 6.2 8 4.5 4.5 0 0 0 5 17Z"/>,
  rectangle: <rect x="4" y="6" width="16" height="12" rx="1.5"/>,
  circle: <circle cx="12" cy="12" r="7.5"/>,
  arrow: <><path d="M5 19 19 5M11 5h8v8"/></>,
  pencil: <><path d="m4 20 4.2-1 10.9-10.9a2.2 2.2 0 0 0-3.2-3.2L5 15.8 4 20Z"/><path d="m14.5 6.5 3 3"/></>,
  dimension: <><path d="M4 7v10M20 7v10M4 12h16"/><path d="m8 9-3 3 3 3M16 9l3 3-3 3"/></>,
  cursor: <path d="m5 3 13 8-6 1.5L9 19 5 3Z"/>,
  undo: <><path d="m8 8-4 4 4 4"/><path d="M5 12h8a6 6 0 0 1 6 6"/></>,
  redo: <><path d="m16 8 4 4-4 4"/><path d="M19 12h-8a6 6 0 0 0-6 6"/></>,
  grid: <><path d="M4 4h16v16H4Z"/><path d="M4 10h16M10 4v16"/></>,
  feed: <><path d="M5 5h14v14H5Z"/><path d="M8 9h8M8 12h8M8 15h5"/></>,
  user: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
  filters: <><path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h7M15 18h5"/><circle cx="16" cy="6" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="13" cy="18" r="2"/></>,
  cart: <><path d="M3 4h2l2 11h10l3-8H6"/><circle cx="9" cy="20" r="1" fill="currentColor" stroke="none"/><circle cx="17" cy="20" r="1" fill="currentColor" stroke="none"/></>,
  photo: <><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m4 17 5-5 4 4 2-2 5 5"/></>,
};

export function NavIcon({ name, ...props }: { name: NavIconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {paths[name]}
    </svg>
  );
}
