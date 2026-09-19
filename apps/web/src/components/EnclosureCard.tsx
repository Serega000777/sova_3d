"use client";

/**
 * A case for a board (T-157/T-158, F-035/F-036): pick a component the catalogue knows, say
 * what the walls and the lid should be, get a tray on standoffs with every port open and a
 * lid that drops in — two bodies, each a file, both editable afterwards like any AI plan.
 */
import type { Component, EnclosureBody } from "@physical-ai/contracts";
import { useMemo, useState } from "react";

export interface EnclosureCardProps {
  components: Component[];
  language: "en" | "ru";
  disabled: boolean;
  onBuild: (body: Omit<EnclosureBody, "workspace_id" | "project_id">) => Promise<void>;
}

const HOUSED = new Set(["board", "display", "sensor", "battery"]);

const T = {
  en: {
    title: "A case for a board",
    blurb:
      "Raspberry Pi, Arduino, ESP32 and the rest: the catalogue knows the outline, the mounting holes and where the ports are. The tray gets standoffs drilled for the board's own screws and an opening for every port; the lid drops in.",
    component: "Component",
    wall: "Wall (mm)",
    clearance: "Clearance (mm)",
    headroom: "Headroom (mm)",
    radius: "Corner radius (mm)",
    lid: "With a lid",
    fan: "Fan on the lid",
    noFan: "vent slots",
    build: "Build the case",
    building: "Building…",
    size: "board",
    ports: "ports",
    holes: "holes",
  },
  ru: {
    title: "Корпус под плату",
    blurb:
      "Raspberry Pi, Arduino, ESP32 и другие: каталог знает контур, крепёжные отверстия и где разъёмы. Поддон получает стойки под родные винты и вырез под каждый разъём; крышка вставляется сверху.",
    component: "Компонент",
    wall: "Стенка (мм)",
    clearance: "Зазор (мм)",
    headroom: "Запас сверху (мм)",
    radius: "Скругление углов (мм)",
    lid: "С крышкой",
    fan: "Вентилятор на крышке",
    noFan: "щели",
    build: "Построить корпус",
    building: "Строим…",
    size: "плата",
    ports: "разъёмов",
    holes: "отверстия",
  },
};

export function EnclosureCard({ components, language, disabled, onBuild }: EnclosureCardProps) {
  const t = T[language];
  const housed = useMemo(() => components.filter((c) => HOUSED.has(c.kind)), [components]);
  const fans = useMemo(() => components.filter((c) => c.kind === "fan"), [components]);
  const [componentId, setComponentId] = useState<string>("");
  const [wall, setWall] = useState(2);
  const [clearance, setClearance] = useState(1);
  const [headroom, setHeadroom] = useState(2);
  const [radius, setRadius] = useState(2);
  const [lid, setLid] = useState(true);
  const [fanId, setFanId] = useState<string>("");
  const [building, setBuilding] = useState(false);

  const chosen = housed.find((c) => c.id === (componentId || housed[0]?.id));
  if (housed.length === 0) return null;

  async function build() {
    if (!chosen) return;
    setBuilding(true);
    try {
      await onBuild({
        component_id: chosen.id,
        wall_mm: wall,
        clearance_mm: clearance,
        headroom_mm: headroom,
        corner_radius_mm: radius,
        lid,
        fan_id: lid && fanId ? fanId : null,
        vents: true,
        label: null,
        material_id: null,
      });
    } finally {
      setBuilding(false);
    }
  }

  const number = (
    label: string,
    value: number,
    set: (v: number) => void,
    min: number,
    max: number,
    step = 0.5,
  ) => (
    <label className="muted" style={{ fontSize: 12 }}>
      {label}
      <input
        className="input"
        type="number"
        style={{ width: 88, display: "block" }}
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled || building}
        onChange={(event) => set(Number(event.target.value))}
      />
    </label>
  );

  return (
    <div className="card stack" data-testid="enclosure-card">
      <strong>{t.title}</strong>
      <span className="muted">{t.blurb}</span>
      <div className="row" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
        <label className="muted" style={{ fontSize: 12 }}>
          {t.component}
          <select
            className="input"
            style={{ display: "block", minWidth: 220 }}
            value={chosen?.id ?? ""}
            disabled={disabled || building}
            onChange={(event) => setComponentId(event.target.value)}
          >
            {housed.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        {number(t.wall, wall, setWall, 1, 6)}
        {number(t.clearance, clearance, setClearance, 0.2, 5, 0.1)}
        {number(t.headroom, headroom, setHeadroom, 0, 30)}
        {number(t.radius, radius, setRadius, 0, 5)}
      </div>
      {chosen && (
        <span className="muted" style={{ fontSize: 12 }}>
          {t.size} {chosen.size_mm[0]} × {chosen.size_mm[1]} mm · {chosen.holes.length} {t.holes}{" "}
          {chosen.screw} · {chosen.cutouts.length} {t.ports}
          {chosen.note ? ` · ${chosen.note}` : ""}
        </span>
      )}
      <div className="row" style={{ flexWrap: "wrap" }}>
        <label className="muted" style={{ fontSize: 12 }}>
          <input
            type="checkbox"
            checked={lid}
            disabled={disabled || building}
            onChange={(event) => setLid(event.target.checked)}
          />{" "}
          {t.lid}
        </label>
        {lid && (
          <label className="muted" style={{ fontSize: 12 }}>
            {t.fan}{" "}
            <select
              className="input"
              value={fanId}
              disabled={disabled || building}
              onChange={(event) => setFanId(event.target.value)}
            >
              <option value="">— {t.noFan}</option>
              {fans.map((fan) => (
                <option key={fan.id} value={fan.id}>
                  {fan.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          type="button"
          className="btn primary"
          disabled={disabled || building || !chosen}
          onClick={() => void build()}
        >
          {building ? t.building : t.build}
        </button>
      </div>
    </div>
  );
}
