import type { ReactNode, SVGProps } from "react";

export type StudioToolIconName =
  | "catalog" | "chat" | "shape" | "cad" | "detail" | "transform" | "scene"
  | "furniture" | "mechanism" | "site" | "facade" | "photo" | "region" | "paint"
  | "size" | "measure" | "reverse" | "repair" | "engineer" | "fit" | "parts"
  | "print" | "export" | "versions" | "history" | "origin" | "licence" | "market"
  | "transfer" | "training" | "more";

const paths: Record<StudioToolIconName, ReactNode> = {
  catalog: <><circle cx="10" cy="10" r="5.5"/><path d="m14 14 5 5M4 20h16"/></>,
  chat: <><path d="M4 5h16v11H9l-5 4V5Z"/><path d="m13 7 .8 2.2L16 10l-2.2.8L13 13l-.8-2.2L10 10l2.2-.8Z"/></>,
  shape: <><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/></>,
  cad: <><path d="M4 19 15 8l3 3L7 22H4v-3ZM14 5l2-2 5 5-2 2"/><path d="M4 4h7"/></>,
  detail: <><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M22 12h-3M12 22v-3M2 12h3"/></>,
  transform: <><path d="M5 19 19 5M11 5h8v8"/><path d="M5 9V5h4M15 19h4v-4"/></>,
  scene: <><path d="m4 7 8-4 8 4-8 4-8-4Z"/><path d="m4 12 8 4 8-4M4 17l8 4 8-4"/></>,
  furniture: <><path d="M5 13h14v7M7 13V8h10v5M5 20v2M19 20v2"/><path d="M3 13h18"/></>,
  mechanism: <><circle cx="8" cy="12" r="4"/><circle cx="16" cy="12" r="4"/><path d="M11 12h2"/></>,
  site: <><path d="M4 18 8 7l4 5 4-8 4 14Z"/><path d="M3 20h18"/></>,
  facade: <><path d="m3 10 9-7 9 7v11H3V10Z"/><path d="M8 21v-7h8v7M3 10h18"/></>,
  photo: <><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m4 17 5-5 4 4 2-2 5 5"/></>,
  region: <><path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/><path d="M8 12h8"/></>,
  paint: <><path d="M4 20c3 0 4-1 4-4l9-9 3 3-9 9c-3 0-4 1-4 3"/><path d="m15 5 2-2 4 4-2 2"/></>,
  size: <><path d="M4 7v10M20 7v10M4 12h16"/><path d="m8 9-3 3 3 3M16 9l3 3-3 3"/></>,
  measure: <><path d="M4 18 18 4l3 3L7 21 4 18Z"/><path d="m9 16-2-2M12 13l-2-2M15 10l-2-2"/></>,
  reverse: <><path d="M4 7h13M14 4l3 3-3 3M20 17H7M10 14l-3 3 3 3"/></>,
  repair: <><path d="M14 6a4 4 0 0 0-5 5L3 17l4 4 6-6a4 4 0 0 0 5-5l-3 2-3-3 2-3Z"/></>,
  engineer: <><circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/></>,
  fit: <><rect x="3" y="5" width="11" height="11" rx="2"/><rect x="10" y="8" width="11" height="11" rx="2"/></>,
  parts: <><circle cx="6" cy="7" r="2"/><circle cx="6" cy="17" r="2"/><path d="m8 8 11 8M8 16 19 8"/></>,
  print: <><path d="M6 9V3h12v6M6 18H4V9h16v9h-2"/><rect x="7" y="14" width="10" height="7"/></>,
  export: <><path d="M12 15V3M7 8l5-5 5 5M5 13v7h14v-7"/></>,
  versions: <><path d="M4 12a8 8 0 1 0 2.3-5.7L4 8.5"/><path d="M4 4v4.5h4.5M12 8v5l3 2"/></>,
  history: <><path d="M7 6h13M7 12h13M7 18h13"/><circle cx="3.5" cy="6" r=".8" fill="currentColor"/><circle cx="3.5" cy="12" r=".8" fill="currentColor"/><circle cx="3.5" cy="18" r=".8" fill="currentColor"/></>,
  origin: <><circle cx="5" cy="5" r="2"/><circle cx="19" cy="8" r="2"/><circle cx="19" cy="18" r="2"/><path d="M7 5h3a4 4 0 0 1 4 4v5a4 4 0 0 0 4 4M14 10a4 4 0 0 1 4-2"/></>,
  licence: <><path d="M6 3h9l3 3v15H6V3Z"/><path d="M15 3v4h4M9 12h6M9 16h5"/></>,
  market: <><path d="M4 9.5h16l-1.2 10H5.2L4 9.5Z"/><path d="M7 9.5 8.5 4h7L17 9.5"/></>,
  transfer: <><path d="M4 12h14M14 7l5 5-5 5"/><path d="M4 5v14"/></>,
  training: <><ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7"/></>,
  more: <><circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/></>,
};

export function StudioToolIcon({ name, ...props }: { name: StudioToolIconName } & SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>;
}
