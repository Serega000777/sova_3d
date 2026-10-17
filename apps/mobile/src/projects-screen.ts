export type TemplateVisual = {
  glyph: string;
  categoryLabel: string;
};

const TEMPLATE_GLYPHS: Record<string, string> = {
  organizer: "▦",
  "phone-stand": "◢",
  "pipe-holder": "∩",
  "mounting-plate": "▭",
  "battery-tray": "▥",
  puck: "●",
};

const CATEGORY_LABELS: Record<string, string> = {
  home: "Для дома",
  desk: "Рабочий стол",
  workshop: "Мастерская",
  learn: "Для старта",
};

/** Honest visual metadata: these are icons, never synthetic product thumbnails. */
export function templateVisual(id: string, category: string): TemplateVisual {
  return {
    glyph: TEMPLATE_GLYPHS[id] ?? "◇",
    categoryLabel: CATEGORY_LABELS[category] ?? category,
  };
}

export function listingPrice(priceCents: number, currency: string): string {
  return priceCents === 0 ? "Бесплатно" : `${(priceCents / 100).toFixed(2)} ${currency}`;
}
