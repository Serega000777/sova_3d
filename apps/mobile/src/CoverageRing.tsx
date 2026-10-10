/**
 * Live walk-around coverage for object capture (item 05 follow-up). One ring of sectors,
 * not a sphere: the only real per-frame signal is a single gyro-integrated azimuth
 * (`ScanTracker.sectorCoverage`), so this deliberately shows "which side of the object
 * you've covered", never a precise elevation/pose map the sensors cannot back.
 */
import Svg, { Circle, Path } from "react-native-svg";

import { colors } from "@/src/theme";

function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const rad = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

function ringSegmentPath(
  cx: number,
  cy: number,
  rOuter: number,
  rInner: number,
  startDeg: number,
  endDeg: number,
): string {
  const [x1, y1] = polar(cx, cy, rOuter, startDeg);
  const [x2, y2] = polar(cx, cy, rOuter, endDeg);
  const [x3, y3] = polar(cx, cy, rInner, endDeg);
  const [x4, y4] = polar(cx, cy, rInner, startDeg);
  const largeArc = endDeg - startDeg > 180 ? 1 : 0;
  return [
    `M ${x1} ${y1}`,
    `A ${rOuter} ${rOuter} 0 ${largeArc} 1 ${x2} ${y2}`,
    `L ${x3} ${y3}`,
    `A ${rInner} ${rInner} 0 ${largeArc} 0 ${x4} ${y4}`,
    "Z",
  ].join(" ");
}

export function CoverageRing({
  covered,
  size = 108,
}: {
  covered: boolean[];
  size?: number;
}) {
  const sectorCount = covered.length;
  if (sectorCount === 0) return null;
  const cx = size / 2;
  const cy = size / 2;
  const rOuter = size / 2 - 4;
  const rInner = rOuter - 16;
  const sectorAngle = 360 / sectorCount;
  const gapDeg = Math.min(4, sectorAngle / 4);

  return (
    <Svg width={size} height={size}>
      <Circle cx={cx} cy={cy} r={rInner - 5} fill="none" stroke={colors.border} strokeWidth={1} />
      {covered.map((isCovered, i) => (
        <Path
          key={i}
          d={ringSegmentPath(
            cx,
            cy,
            rOuter,
            rInner,
            i * sectorAngle + gapDeg / 2,
            (i + 1) * sectorAngle - gapDeg / 2,
          )}
          fill={isCovered ? colors.accent : colors.border}
        />
      ))}
    </Svg>
  );
}
