/**
 * Ask the engineer on the phone (T-119, F-005): the same verdicts as the web, one tap to
 * apply a fix. Runs in Expo Go — plain React Native, no native modules.
 */
import type { EngineeringAnswer, EngineeringReport, EngineeringReportBody, Job } from "@physical-ai/contracts";
import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { engineeringVerdictTone } from "./engineering-verdict";
import { colors, styles } from "./theme";

type Language = "ru" | "en";

const EXAMPLES: Record<Language, string[]> = {
  ru: [
    "Эта стенка слишком тонкая?",
    "Выдержит ли она 5 кг?",
    "Какой пластик выбрать для улицы?",
    "Отверстия под винты M5",
  ],
  en: [
    "Is this wall too thin?",
    "Will it hold 5 kg?",
    "Which plastic should I use outdoors?",
    "Holes for M5 screws",
  ],
};

const MATERIALS = ["pla", "petg", "abs", "tpu", "asa"];

export interface EngineerCardProps {
  language: Language;
  disabled: boolean;
  hasRegion: boolean;
  history: EngineeringReport[];
  onAsk: (body: {
    question: string | null;
    purpose: string | null;
    material_id: string;
  }) => Promise<Job | null>;
  onApplyFix: (fix: NonNullable<EngineeringAnswer["fix"]>) => Promise<void>;
}

function storedAnswer(row: EngineeringReport): EngineeringAnswer | null {
  const report = row.report;
  if (!report || typeof report !== "object") return null;
  const answer = (report as Record<string, unknown>).answer;
  if (!answer || typeof answer !== "object") return null;
  const record = answer as Record<string, unknown>;
  if (typeof record.summary !== "string" || typeof record.intent !== "string") return null;
  return answer as unknown as EngineeringAnswer;
}

function verdictColour(answer: EngineeringAnswer): string {
  const tone = engineeringVerdictTone(answer.intent, answer.verdict);
  return tone === "positive" ? colors.green : tone === "negative" ? colors.red : colors.yellow;
}

function AnswerView({
  answer,
  language,
  disabled,
  onApplyFix,
}: {
  answer: EngineeringAnswer;
  language: Language;
  disabled: boolean;
  onApplyFix: EngineerCardProps["onApplyFix"];
}) {
  const ru = language === "ru";
  const fix = answer.fix;
  return (
    <View style={{ gap: 6 }}>
      <Text style={styles.text}>
        <Text style={{ color: verdictColour(answer), fontWeight: "600" }}>
          {answer.intent}
        </Text>
        {"  "}
        {answer.summary}
      </Text>
      {answer.reasons.map((reason) => (
        <Text key={reason} style={styles.muted}>
          · {reason}
        </Text>
      ))}
      {answer.recommendation && <Text style={styles.text}>{answer.recommendation}</Text>}
      {fix && (
        <Pressable
          style={[styles.button, styles.buttonPrimary, disabled && { opacity: 0.5 }]}
          disabled={disabled}
          onPress={() => void onApplyFix(fix)}
        >
          <Text style={styles.buttonText}>
            {ru ? "Применить" : "Apply"}: {fix.label}
          </Text>
        </Pressable>
      )}
      <Text style={[styles.muted, { fontSize: 11 }]}>
        {ru ? "уверенность" : "confidence"} {answer.confidence} ·{" "}
        {ru ? "ориентировочная оценка для настольной FDM-печати" : "rules of thumb for desktop FDM"}
      </Text>
    </View>
  );
}

export function EngineerCard({ language, disabled, hasRegion, history, onAsk, onApplyFix }: EngineerCardProps) {
  const ru = language === "ru";
  const examples = EXAMPLES[language];
  const [question, setQuestion] = useState("");
  const [purpose, setPurpose] = useState("");
  const [material, setMaterial] = useState("pla");
  const [report, setReport] = useState<EngineeringReportBody | null>(null);
  const [busy, setBusy] = useState(false);

  async function ask() {
    setBusy(true);
    try {
      const job = await onAsk({
        question: question.trim() || null,
        purpose: purpose.trim() || null,
        material_id: material,
      });
      const result = job?.result as { report?: EngineeringReportBody } | null;
      if (result?.report) setReport(result.report);
    } finally {
      setBusy(false);
    }
  }

  const facts = report?.facts;
  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <Text style={styles.heading}>{ru ? "Спросить инженера" : "Ask the engineer"}</Text>
        {hasRegion && (
          <Text style={styles.muted}>
            {ru ? "о выделенной области" : "about the outlined area"}
          </Text>
        )}
      </View>
      <TextInput
        style={styles.input}
        value={question}
        onChangeText={setQuestion}
        placeholder={examples[0]}
        placeholderTextColor={colors.muted}
        editable={!disabled && !busy}
      />
      <TextInput
        style={styles.input}
        value={purpose}
        onChangeText={setPurpose}
        placeholder={ru ? "Для чего эта деталь?" : "What is it for?"}
        placeholderTextColor={colors.muted}
        editable={!disabled && !busy}
      />
      <View style={styles.row}>
        {MATERIALS.map((id) => (
          <Pressable
            key={id}
            style={[styles.chip, material === id && { borderColor: colors.accent }]}
            onPress={() => setMaterial(id)}
          >
            <Text style={[styles.chipText, material === id && { color: colors.accent }]}>
              {id.toUpperCase()}
            </Text>
          </Pressable>
        ))}
      </View>
      <View style={styles.row}>
        {examples.map((example) => (
          <Pressable key={example} style={styles.chip} onPress={() => setQuestion(example)}>
            <Text style={styles.chipText}>{example}</Text>
          </Pressable>
        ))}
      </View>
      <Pressable
        style={[styles.button, styles.buttonPrimary, (disabled || busy) && { opacity: 0.5 }]}
        disabled={disabled || busy}
        onPress={() => void ask()}
      >
        <Text style={styles.buttonText}>
          {busy
            ? ru
              ? "Измеряем…"
              : "Measuring…"
            : question.trim()
              ? ru
                ? "Спросить"
                : "Ask"
              : ru
                ? "Проверить деталь"
                : "Review the part"}
        </Text>
      </Pressable>

      {report?.answer && (
        <AnswerView
          answer={report.answer}
          language={language}
          disabled={disabled}
          onApplyFix={onApplyFix}
        />
      )}
      {facts && (
        <Text style={styles.muted}>
          {facts.walls
            ? ru
              ? `стенки от ${facts.walls.min_mm} мм · `
              : `walls from ${facts.walls.min_mm} mm · `
            : ""}
          {ru ? "рекомендуется" : "recommended"} {report?.recommended_wall_mm}{" "}
          {ru ? "мм для" : "mm for"} {report?.material_id.toUpperCase()}
          {facts.mass_g[report?.material_id ?? ""] != null
            ? ` · ${facts.mass_g[report?.material_id ?? ""]} ${ru ? "г" : "g"}`
            : ""}
        </Text>
      )}
      {report && report.materials.length > 0 && (
        <View style={styles.row}>
          {report.materials.slice(0, 3).map((choice, index) => (
            <View
              key={choice.id}
              style={[styles.chip, index === 0 && { borderColor: colors.accent }]}
            >
              <Text style={styles.chipText}>
                {choice.name}
                {choice.mass_g != null ? ` · ${choice.mass_g} ${ru ? "г" : "g"}` : ""}
              </Text>
            </View>
          ))}
        </View>
      )}
      {report && report.recommendations.length > 0 && (
        <View style={{ gap: 10 }}>
          <Text style={styles.muted}>
            {ru ? "Инженер также заметил:" : "The engineer also noticed:"}
          </Text>
          {report.recommendations.map((item, index) => (
            <AnswerView
              key={`${item.intent}-${index}`}
              answer={item}
              language={language}
              disabled={disabled}
              onApplyFix={onApplyFix}
            />
          ))}
        </View>
      )}
      {history.length > 0 && (
        <View style={{ gap: 8 }} accessibilityLabel={ru ? "История инженерных проверок" : "Engineering history"}>
          <Text style={styles.heading}>{ru ? "Предыдущие проверки" : "Previous checks"}</Text>
          <Text style={styles.muted}>
            {ru
              ? "Сохранены сервером для этой версии. Это эвристики FDM, а не подтверждение допустимой нагрузки."
              : "Stored by the server for this version. These are FDM heuristics, not certified load results."}
          </Text>
          {history.slice(0, 5).map((item) => {
            const answer = storedAnswer(item);
            return (
              <View key={item.id} style={{ gap: 3, paddingLeft: 10, borderLeftWidth: 2, borderLeftColor: colors.border }}>
                <Text style={styles.text}>{item.question || (ru ? "Общая проверка детали" : "General part review")}</Text>
                {answer && (
                  <Text style={[styles.sectionSubtitle, { color: verdictColour(answer) }]}>
                    {answer.summary}
                  </Text>
                )}
                <Text style={styles.muted}>
                  {new Date(item.created_at).toLocaleString(ru ? "ru-RU" : "en-GB")}
                  {item.material_id ? ` · ${item.material_id.toUpperCase()}` : ""}
                  {item.region ? (ru ? " · выделенная область" : " · selected region") : ""}
                </Text>
              </View>
            );
          })}
        </View>
      )}
    </View>
  );
}
