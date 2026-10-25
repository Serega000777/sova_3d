import type { Listing } from "@physical-ai/contracts";

type Language = "en" | "ru";
type Facade = NonNullable<Listing["facade"]>;

const SIDE_LABELS = {
  front: { ru: "Передний", en: "Front" },
  back: { ru: "Задний", en: "Back" },
  left: { ru: "Левый", en: "Left" },
  right: { ru: "Правый", en: "Right" },
} as const;

const KIND_LABELS = {
  window: { ru: "Окно", en: "Window" },
  door: { ru: "Дверь", en: "Door" },
  opening: { ru: "Проём", en: "Opening" },
} as const;

const ROOF_LABELS = {
  none: { ru: "Без крыши", en: "No roof" },
  flat: { ru: "Плоская", en: "Flat" },
  gable: { ru: "Двускатная", en: "Gable" },
  shed: { ru: "Односкатная", en: "Shed" },
  hip: { ru: "Вальмовая", en: "Hip" },
} as const;

export function MarketplaceFacadeSchedule({ facade, language }: { facade: Facade; language: Language }) {
  const ru = language === "ru";

  return (
    <section className="card stack" aria-label={ru ? "Спецификация фасада" : "Facade schedule"}>
      <div>
        <strong>{ru ? "Спецификация фасада" : "Facade schedule"}</strong>
        <div className="muted">
          {ru
            ? "Параметры восстановлены из успешной неизменяемой операции фасада — это не чертёж DWG."
            : "Parameters recovered from the successful immutable facade operation — not a DWG drawing."}
        </div>
      </div>
      <div className="row">
        <span className="chip">{ru ? "Крыша" : "Roof"}: {ROOF_LABELS[facade.roof][language]}</span>
        <span className="chip mono">{ru ? "Стена" : "Wall"}: {facade.wall_thickness_mm.toFixed(0)} mm</span>
        <span className="chip mono">{ru ? "Высота этажа" : "Floor height"}: {facade.floor_height_mm.toFixed(0)} mm</span>
        {facade.roof !== "none" && (
          <span className="chip mono">{ru ? "Свес" : "Overhang"}: {facade.overhang_mm.toFixed(0)} mm</span>
        )}
      </div>
      {facade.openings.length > 0 ? (
        <ul className="list">
          {facade.openings.map((opening) => (
            <li className="row" key={opening.opening_id} style={{ justifyContent: "space-between" }}>
              <span>
                <strong>{KIND_LABELS[opening.kind][language]}</strong>
                {` · ${SIDE_LABELS[opening.side][language]}`}
                {opening.floor ? ` · ${ru ? "этаж" : "floor"} ${opening.floor}` : ""}
              </span>
              <span className="mono">
                {opening.width_mm.toFixed(0)} × {opening.height_mm.toFixed(0)} mm
                {opening.sill_mm > 0 ? ` · ${ru ? "подоконник" : "sill"} ${opening.sill_mm.toFixed(0)} mm` : ""}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <span className="muted">{ru ? "Адресные проёмы не сохранены." : "No addressed openings were saved."}</span>
      )}
    </section>
  );
}
