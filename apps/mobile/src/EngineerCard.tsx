/**
 * Ask the engineer on the phone (T-119, F-005): the same verdicts as the web, one tap to
 * apply a fix. Runs in Expo Go — plain React Native, no native modules.
 */
import type { EngineeringAnswer, EngineeringReportBody, Job } from "@physical-ai/contracts";
import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { colors, styles } from "./theme";

const EXAMPLES = [
  "Эта стенка слишком тонкая?",
  "Will it hold 5 kg?",
  "Какой пластик выбрать для улицы?",
  "Holes for M5 screws",
];

const MATERIALS = ["pla", "petg", "abs", "tpu", "asa"];

export interface EngineerCardProps {
  disabled: boolean;
  hasRegion: boolean;
  onAsk: (body: {
    question: string | null;
    purpose: string | null;
    material_id: string;
  }) => Promise<Job | null>;
  onApplyFix: (fix: NonNullable<EngineeringAnswer["fix"]>) => Promise<void>;
}

function verdictColour(verdict: EngineeringAnswer["verdict"]): string {
  // "yes" answers "is something wrong?" — so yes is the worrying one
  return verdict === "yes" ? colors.red : verdict === "no" ? colors.green : colors.yellow;
}

function AnswerView({
  answer,
  disabled,
  onApplyFix,
}: {
  answer: EngineeringAnswer;
  disabled: boolean;
  onApplyFix: EngineerCardProps["onApplyFix"];
}) {
  const fix = answer.fix;
  return (
    <View style={{ gap: 6 }}>
      <Text style={styles.text}>
        <Text style={{ color: verdictColour(answer.verdict), fontWeight: "600" }}>
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
          <Text style={styles.buttonText}>Apply: {fix.label}</Text>
        </Pressable>
      )}
      <Text style={[styles.muted, { fontSize: 11 }]}>
        confidence {answer.confidence} · rules of thumb for desktop FDM
      </Text>
    </View>
  );
}

export function EngineerCard({ disabled, hasRegion, onAsk, onApplyFix }: EngineerCardProps) {
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
        <Text style={styles.heading}>Ask the engineer</Text>
        {hasRegion && <Text style={styles.muted}>about the outlined area</Text>}
      </View>
      <TextInput
        style={styles.input}
        value={question}
        onChangeText={setQuestion}
        placeholder={EXAMPLES[0]}
        placeholderTextColor={colors.muted}
        editable={!disabled && !busy}
      />
      <TextInput
        style={styles.input}
        value={purpose}
        onChangeText={setPurpose}
        placeholder="What is it for?"
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
        {EXAMPLES.map((example) => (
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
          {busy ? "Measuring…" : question.trim() ? "Ask" : "Review the part"}
        </Text>
      </Pressable>

      {report?.answer && (
        <AnswerView answer={report.answer} disabled={disabled} onApplyFix={onApplyFix} />
      )}
      {facts && (
        <Text style={styles.muted}>
          {facts.walls ? `walls from ${facts.walls.min_mm} mm · ` : ""}
          recommended {report?.recommended_wall_mm} mm for {report?.material_id.toUpperCase()}
          {facts.mass_g[report?.material_id ?? ""] != null
            ? ` · ${facts.mass_g[report?.material_id ?? ""]} g`
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
                {choice.mass_g != null ? ` · ${choice.mass_g} g` : ""}
              </Text>
            </View>
          ))}
        </View>
      )}
      {report && report.recommendations.length > 0 && (
        <View style={{ gap: 10 }}>
          <Text style={styles.muted}>The engineer also noticed:</Text>
          {report.recommendations.map((item, index) => (
            <AnswerView
              key={`${item.intent}-${index}`}
              answer={item}
              disabled={disabled}
              onApplyFix={onApplyFix}
            />
          ))}
        </View>
      )}
    </View>
  );
}
