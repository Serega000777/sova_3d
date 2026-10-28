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

export function MicrophoneIcon(props: IconProps) {
  return <IconFrame {...props}><Rect x="9" y="3" width="6" height="11" rx="3" /><Path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M9 21h6" /></IconFrame>;
}

export function PinIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="M12 21s6-5.2 6-11a6 6 0 1 0-12 0c0 5.8 6 11 6 11Z" /><Circle cx="12" cy="10" r="2" /></IconFrame>;
}

export function HandIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="M7 11V7.5a1.5 1.5 0 0 1 3 0V10m0-4.5a1.5 1.5 0 0 1 3 0V10m0-3.5a1.5 1.5 0 0 1 3 0v4m0-2a1.5 1.5 0 0 1 3 0V14c0 4-2.5 7-7 7-3.2 0-5.1-1.5-6.5-4L3 12.8a1.5 1.5 0 0 1 2.4-1.7L7 12.5Z" /></IconFrame>;
}

export function CloudIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="M5 17h13a4 4 0 0 0 .4-8A6.5 6.5 0 0 0 6.2 8 4.5 4.5 0 0 0 5 17Z" /></IconFrame>;
}

export function RectangleIcon(props: IconProps) {
  return <IconFrame {...props}><Rect x="4" y="6" width="16" height="12" rx="1.5" /></IconFrame>;
}

export function CircleIcon(props: IconProps) {
  return <IconFrame {...props}><Circle cx="12" cy="12" r="7.5" /></IconFrame>;
}

export function DirectionIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="M5 19 19 5M11 5h8v8" /></IconFrame>;
}

export function PencilIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="m4 20 4.2-1 10.9-10.9a2.2 2.2 0 0 0-3.2-3.2L5 15.8 4 20Z" /><Path d="m14.5 6.5 3 3" /></IconFrame>;
}

export function DimensionIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="M4 7v10M20 7v10M4 12h16" /><Path d="m8 9-3 3 3 3M16 9l3 3-3 3" /></IconFrame>;
}

export function CursorIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="m5 3 13 8-6 1.5L9 19 5 3Z" /></IconFrame>;
}

export function CheckIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="m5 12 4 4L19 6" /></IconFrame>;
}

export function BoxIcon(props: IconProps) {
  return <IconFrame {...props}><Path d="m12 3 8 4.5v9L12 21l-8-4.5v-9Z" /><Path d="m4 7.5 8 4.5 8-4.5M12 12v9" /></IconFrame>;
}
