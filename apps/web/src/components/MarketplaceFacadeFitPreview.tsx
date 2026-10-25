"use client";

import type { FacadeCompatibility } from "@physical-ai/contracts";
import { useEffect, useMemo, useState } from "react";

import {
  type FacadeSide,
  facadePreviewGeometry,
} from "@/lib/facade-fit-preview";

const SIDES: FacadeSide[] = ["front", "back", "left", "right"];
const SIDE_LABELS: Record<FacadeSide, { en: string; ru: string }> = {
  front: { en: "Front", ru: "Главный" },
  back: { en: "Back", ru: "Задний" },
  left: { en: "Left", ru: "Левый" },
  right: { en: "Right", ru: "Правый" },
};

export function MarketplaceFacadeFitPreview({
  compatibility,
  language,
}: {
  compatibility: FacadeCompatibility;
  language: "en" | "ru";
}) {
  const ru = language === "ru";
  const availableSides = useMemo(() => SIDES.filter((candidate) => (
    compatibility.openings.some((opening) => opening.side === candidate)
  )), [compatibility.openings]);
  const firstMatched = compatibility.openings.find((opening) => opening.matches.length > 0)
    ?? compatibility.openings[0];
  const [side, setSide] = useState<FacadeSide>(firstMatched?.side ?? "front");
  const [openingId, setOpeningId] = useState(firstMatched?.opening_id ?? "");
  const [matchVersionId, setMatchVersionId] = useState(firstMatched?.matches[0]?.version_id ?? "");
  const geometry = useMemo(
    () => facadePreviewGeometry(compatibility, side),
    [compatibility, side],
  );
  const sideOpenings = compatibility.openings.filter((opening) => opening.side === side);
  const selectedOpening = sideOpenings.find((opening) => opening.opening_id === openingId)
    ?? geometry?.openings[0]
    ?? null;
  const selectedMatch = selectedOpening?.matches.find((match) => match.version_id === matchVersionId)
    ?? selectedOpening?.matches[0]
    ?? null;

  useEffect(() => {
    if (!availableSides.includes(side)) setSide(availableSides[0] ?? "front");
  }, [availableSides, side]);

  useEffect(() => {
    const openings = compatibility.openings.filter((opening) => opening.side === side);
    if (openings.some((opening) => opening.opening_id === openingId)) return;
    const next = openings.find((opening) => opening.matches.length > 0) ?? openings[0];
    setOpeningId(next?.opening_id ?? "");
    setMatchVersionId(next?.matches[0]?.version_id ?? "");
  }, [compatibility.openings, openingId, side]);

  if (!geometry || availableSides.length === 0) return null;
  const chooseOpening = (id: string) => {
    const opening = compatibility.openings.find((candidate) => candidate.opening_id === id);
    setOpeningId(id);
    setMatchVersionId(opening?.matches[0]?.version_id ?? "");
  };
  return (
    <div className="card stack marketplace-facade-fit-preview">
      <div>
        <strong>{ru ? "Схема примерки на фасаде" : "Facade fit diagram"}</strong>
        <div className="muted">
          {ru
            ? "Выберите сторону и адресный проём. Схема построена по сохранённой геометрии exact-фасада."
            : "Choose a side and an addressed opening. The diagram uses the saved exact-facade geometry."}
        </div>
      </div>
      <div className="row" role="tablist" aria-label={ru ? "Сторона фасада" : "Facade side"}>
        {availableSides.map((candidate) => (
          <button
            className={`chip ${candidate === side ? "selected" : ""}`}
            key={candidate}
            type="button"
            role="tab"
            aria-selected={candidate === side}
            onClick={() => setSide(candidate)}
          >
            {SIDE_LABELS[candidate][language]}
          </button>
        ))}
      </div>
      <svg
        className="marketplace-facade-fit-svg"
        viewBox={`0 0 ${geometry.width} ${geometry.height}`}
        role="img"
        aria-label={ru ? "Схема проёмов выбранного фасада" : "Openings on the selected facade"}
      >
        <rect className="facade-wall" {...geometry.wall} />
        {geometry.floorLines.map((y) => (
          <line className="facade-floor-line" key={y} x1={geometry.wall.x} x2={geometry.wall.x + geometry.wall.width} y1={y} y2={y} />
        ))}
        {geometry.openings.map((opening) => {
          const selected = opening.opening_id === selectedOpening?.opening_id;
          return (
            <g key={opening.opening_id}>
              <rect
                className={`facade-opening ${opening.matches.length ? "matched" : "unmatched"} ${selected ? "selected" : ""}`}
                x={opening.x}
                y={opening.y}
                width={opening.width}
                height={opening.height}
                rx="3"
              />
              {selected && selectedMatch && (
                <text className="facade-module-label" x={opening.x + opening.width / 2} y={Math.max(18, opening.y - 8)} textAnchor="middle">
                  {selectedMatch.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <label className="stack" style={{ gap: 4, minWidth: 230 }}>
          <span>{ru ? "Адресный проём" : "Addressed opening"}</span>
          <select className="input" value={selectedOpening?.opening_id ?? ""} onChange={(event) => chooseOpening(event.target.value)}>
            {geometry.openings.map((opening) => (
              <option key={opening.opening_id} value={opening.opening_id}>
                {opening.opening_id} · {ru ? "этаж" : "floor"} {opening.floor ?? "—"}
              </option>
            ))}
          </select>
        </label>
        {selectedOpening && selectedOpening.matches.length > 0 && (
          <label className="stack" style={{ gap: 4, minWidth: 230 }}>
            <span>{ru ? "Подходящий модуль" : "Matching module"}</span>
            <select className="input" value={selectedMatch?.version_id ?? ""} onChange={(event) => setMatchVersionId(event.target.value)}>
              {selectedOpening.matches.map((match) => (
                <option key={match.version_id} value={match.version_id}>{match.label}</option>
              ))}
            </select>
          </label>
        )}
      </div>
      {selectedOpening && (
        <span className={selectedMatch ? "status-green" : "status-red"}>
          {selectedMatch
            ? (ru
              ? `${selectedMatch.label}: габарит совпадает с ${selectedOpening.opening_id} (${selectedOpening.side}, этаж ${selectedOpening.floor ?? "—"}).`
              : `${selectedMatch.label}: envelope matches ${selectedOpening.opening_id} (${selectedOpening.side}, floor ${selectedOpening.floor ?? "—"}).`)
            : (ru ? "Для этого проёма нет модуля с совпадающим габаритом." : "No module envelope matches this opening.")}
        </span>
      )}
      <span className="muted">
        {ru
          ? "Это метрическая 2D-схема габарита, а не фоторендер и не доказательство крепежа, монтажного направления, зазоров или mesh-коллизий."
          : "This is a metric 2D envelope diagram, not a photo render or proof of fasteners, mounting direction, clearance or mesh collisions."}
      </span>
    </div>
  );
}
