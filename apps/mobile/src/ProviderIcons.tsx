/** Brand SVGs used by passwordless identity-provider actions. */
import Svg, { Circle, Path, Rect } from "react-native-svg";

export function YandexIdIcon({ size = 48 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 48 48" accessibilityLabel="Яндекс ID">
      <Circle cx="24" cy="24" r="24" fill="#FC3F1D" />
      <Path
        fill="#FFFFFF"
        d="M12.46 29.42H16.29V7.39H10.71C5.1 7.39 2.16 10.27 2.16 14.52C2.16 17.91 3.77 19.91 6.66 21.97L1.65 29.42H5.8L11.38 21.08L9.45 19.78C7.1 18.2 5.96 16.96 5.96 14.3C5.96 11.95 7.61 10.37 10.75 10.37H12.46V29.42Z"
        transform="translate(13 3) scale(1.2)"
      />
    </Svg>
  );
}

export function VkIdIcon({ size = 48 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" accessibilityLabel="VK ID">
      <Rect width="24" height="24" rx="7" fill="#2787F5" />
      <Path
        fill="#FFFFFF"
        d="M6.79 7.3H4.05C4.18 13.54 7.3 17.29 12.77 17.29H13.08V13.72C15.09 13.92 16.61 15.39 17.22 17.29H20.06C19.28 14.45 17.23 12.88 15.95 12.28C17.23 11.54 19.03 9.74 19.46 7.3H16.88C16.32 9.28 14.66 11.08 13.08 11.25V7.3H10.5V14.22C8.9 13.82 6.88 11.88 6.79 7.3Z"
      />
    </Svg>
  );
}
