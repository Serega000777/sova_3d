import type { ReactNode } from "react";
import type { ColorValue } from "react-native";
import Svg, { Circle, Line, Path, Polyline, Rect } from "react-native-svg";

interface IconProps {
  color?: ColorValue;
  size?: number;
  strokeWidth?: number;
}

function IconFrame({ children, color = "currentColor", size = 24, strokeWidth = 1.8 }: IconProps & { children: ReactNode }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      {children}
    </Svg>
  );
}

export function HomeIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z" /></IconFrame>;
}

export function ProjectsIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="M3 7h6l2 2h10v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" /><Path d="M3 7V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2" /></IconFrame>;
}

export function MarketIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="M4 9v11h16V9" /><Path d="M3 4h18l-2 5a3 3 0 0 1-5 1 3 3 0 0 1-4 0 3 3 0 0 1-5-1Z" /><Path d="M9 20v-6h6v6" /></IconFrame>;
}

export function UserIcon(props: IconProps) {
  return <IconFrame {...props}><Circle cx="12" cy="8" r="4" /><Path d="M4 21a8 8 0 0 1 16 0" /></IconFrame>;
}

export function SearchIcon(props: IconProps) {
  return <IconFrame {...props}><Circle cx="11" cy="11" r="7" /><Line x1="16.2" y1="16.2" x2="21" y2="21" /></IconFrame>;
}

export function BellIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><Path d="M10 21h4" /></IconFrame>;
}

export function ArrowRightIcon(props: IconProps) {
  return <IconFrame {...props}><Line x1="5" y1="12" x2="19" y2="12" /><Polyline points="14 7 19 12 14 17" /></IconFrame>;
}

export function MoreIcon(props: IconProps) {
  return <IconFrame {...props}><Circle cx="5" cy="12" r="1" fill={props.color} stroke="none" /><Circle cx="12" cy="12" r="1" fill={props.color} stroke="none" /><Circle cx="19" cy="12" r="1" fill={props.color} stroke="none" /></IconFrame>;
}

export function HousePlanIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="M3 11 12 4l9 7" /><Path d="M5 10v10h14V10" /><Path d="M9 20v-6h6v6" /></IconFrame>;
}

export function Photo3dIcon(props: IconProps) {
  return <IconFrame {...props}><Rect x="3" y="4" width="18" height="16" rx="2" /><Circle cx="9" cy="9" r="2" /><Path d="m4 17 5-5 4 4 2-2 5 5" /></IconFrame>;
}

export function ScanIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3" /><Path d="m8 10 4-2 4 2v5l-4 2-4-2Z" /><Path d="m8 10 4 2 4-2M12 12v5" /></IconFrame>;
}

export function SparklesIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="m12 3 1.3 3.7L17 8l-3.7 1.3L12 13l-1.3-3.7L7 8l3.7-1.3Z" /><Path d="m18 14 .8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8Z" /><Path d="m5 13 .6 1.4L7 15l-1.4.6L5 17l-.6-1.4L3 15l1.4-.6Z" /></IconFrame>;
}

export function CubeIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="m12 3 8 4.5v9L12 21l-8-4.5v-9Z" /><Path d="m4 7.5 8 4.5 8-4.5M12 12v9" /></IconFrame>;
}

export function ImportIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="M12 3v12" /><Polyline points="7 10 12 15 17 10" /><Path d="M5 19h14" /></IconFrame>;
}

export function PlusIcon(props: IconProps) {
  return <IconFrame {...props}><Line x1="12" y1="5" x2="12" y2="19" /><Line x1="5" y1="12" x2="19" y2="12" /></IconFrame>;
}
