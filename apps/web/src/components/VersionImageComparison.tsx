"use client";

import { useState } from "react";

export interface ComparisonCrop {
  /** Percentages in the canonical 3:2 thumbnail coordinate system. */
  x: number;
  y: number;
  width: number;
  height: number;
}

function imageStyle(url: string, crop?: ComparisonCrop): React.CSSProperties {
  const style: React.CSSProperties = { backgroundImage: `url(${JSON.stringify(url)})` };
  if (!crop) return { ...style, backgroundPosition: "center", backgroundSize: "cover" };
  const x = Math.max(0, Math.min(crop.x, 100 - crop.width));
  const y = Math.max(0, Math.min(crop.y, 100 - crop.height));
  const positionX = crop.width >= 100 ? 50 : (x / (100 - crop.width)) * 100;
  const positionY = crop.height >= 100 ? 50 : (y / (100 - crop.height)) * 100;
  return {
    ...style,
    backgroundPosition: `${positionX}% ${positionY}%`,
    backgroundRepeat: "no-repeat",
    backgroundSize: `${10000 / crop.width}% ${10000 / crop.height}%`,
  };
}

/** The canonical Source ↔ Current reveal, optionally focused on the same render crop in both versions. */
export function VersionImageComparison({
  beforeUrl,
  currentUrl,
  beforeLabel,
  currentLabel,
  language,
  crop,
}: {
  beforeUrl: string | null;
  currentUrl: string | null;
  beforeLabel: string;
  currentLabel: string;
  language: "ru" | "en";
  crop?: ComparisonCrop;
}) {
  const [ratio, setRatio] = useState(50);
  const ru = language === "ru";
  return (
    <div className="version-compare stack">
      <div className="version-compare-stage">
        {beforeUrl ? (
          <div className="version-compare-image" style={imageStyle(beforeUrl, crop)} role="img" aria-label={beforeLabel} />
        ) : (
          <span className="muted">{ru ? "Нет preview исходной версии" : "No source preview"}</span>
        )}
        <div className="version-compare-current" style={{ width: `${ratio}%` }}>
          {currentUrl ? (
            <div
              className="version-compare-image"
              style={{ ...imageStyle(currentUrl, crop), width: `${10000 / ratio}%` }}
              role="img"
              aria-label={currentLabel}
            />
          ) : null}
        </div>
        <i className="version-compare-divider" style={{ left: `${ratio}%` }} />
        <small className="version-compare-left">{currentLabel}</small>
        <small className="version-compare-right">{beforeLabel}</small>
      </div>
      <label className="stack">
        <span className="muted">{ru ? "Источник ↔ текущая" : "Source ↔ current"}</span>
        <input
          type="range"
          min="4"
          max="96"
          value={ratio}
          onChange={(event) => setRatio(Number(event.target.value))}
        />
      </label>
    </div>
  );
}
