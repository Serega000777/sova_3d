import { useWindowDimensions } from "react-native";

export const TABLET_BREAKPOINT_DP = 600;

export function useIsTablet(): boolean {
  const { width, height } = useWindowDimensions();
  return Math.min(width, height) >= TABLET_BREAKPOINT_DP;
}
