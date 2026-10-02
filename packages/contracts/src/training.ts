/**
 * Self-learning plan steps 1-2 (docs/SELF_LEARNING_PLAN.md): shared UI data for the training
 * consent switch and the result feedback buttons, so web/mobile/desktop show the same wording.
 *
 * Nothing here trains anything — there is no pipeline yet. Step 1 only stores a project
 * owner's opt-in for a future dataset export to filter on; step 2 only stores an explicit
 * quality signal next to the implicit ones (rollback, post-AI edits) that already exist.
 */
import type { FeedbackRating, FeedbackReason } from "./client.js";
import type { Bilingual } from "./create-scenarios.js";

export const TRAINING_CONSENT_COPY = {
  title: { ru: "Помогите улучшить AI", en: "Help improve the AI" } as Bilingual,
  description: {
    ru: "Если включить, запросы к AI и результаты реконструкции этого проекта могут попасть в будущую обучающую выборку. Пока обучения нет — это только разрешение на будущее. Выключить можно в любой момент; это тоже сохраняется.",
    en: "If enabled, this project's AI requests and reconstruction results may be included in a future training dataset. No training happens yet — this only records permission for later. You can turn it off any time; that is recorded too.",
  } as Bilingual,
  ownerOnly: {
    ru: "Изменить может только владелец проекта.",
    en: "Only the project owner can change this.",
  } as Bilingual,
} as const;

export const FEEDBACK_RATINGS: readonly { id: FeedbackRating; label: Bilingual; glyph: string }[] = [
  { id: "good", label: { ru: "Хорошо", en: "Good" }, glyph: "👍" },
  { id: "bad", label: { ru: "Плохо", en: "Bad" }, glyph: "👎" },
  { id: "fixed", label: { ru: "Исправил", en: "Fixed it" }, glyph: "✎" },
];

export const FEEDBACK_REASONS: readonly { id: FeedbackReason; label: Bilingual }[] = [
  {
    id: "prompt_mismatch",
    label: { ru: "Не соответствует описанию", en: "Doesn't match the description" },
  },
  { id: "broken_geometry", label: { ru: "Геометрия сломана", en: "Geometry is broken" } },
  {
    id: "low_detail_quality",
    label: { ru: "Низкое качество деталей", en: "Low detail quality" },
  },
  { id: "other", label: { ru: "Другое", en: "Other" } },
];
