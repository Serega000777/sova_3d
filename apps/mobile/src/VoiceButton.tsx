/**
 * Voice modelling on the phone (T-132, F-017).
 *
 * On web the browser's speech recognition fills the prompt; in Expo Go there is no
 * recogniser and the button says so (a development build with expo-speech-recognition is
 * the route — it is looked up at runtime, never imported). Either way the words go down the
 * same path as typed ones.
 */
import { useEffect, useRef, useState } from "react";
import { Pressable, Text } from "react-native";

import { probe } from "./capabilities";
import { colors, styles } from "./theme";

interface RecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

function recognitionCtor(): (new () => RecognitionLike) | null {
  const scope = globalThis as unknown as {
    SpeechRecognition?: new () => RecognitionLike;
    webkitSpeechRecognition?: new () => RecognitionLike;
  };
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}

export interface VoiceButtonProps {
  onText: (text: string) => void;
  onFinal: (text: string) => void;
  language: "ru" | "en";
  disabled?: boolean;
}

export function VoiceButton({ onText, onFinal, language, disabled }: VoiceButtonProps) {
  const capabilities = probe();
  const [listening, setListening] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const recognition = useRef<RecognitionLike | null>(null);

  useEffect(() => () => recognition.current?.abort(), []);

  if (!capabilities.voice) {
    return <Text style={styles.muted}>{capabilities.voiceReason}</Text>;
  }

  function start() {
    const Ctor = recognitionCtor();
    if (!Ctor) return;
    setNote(null);
    const rec = new Ctor();
    rec.lang = language === "ru" ? "ru-RU" : "en-US";
    rec.interimResults = true;
    rec.continuous = false;
    let finalText = "";
    rec.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) finalText += result[0].transcript;
        else interim += result[0].transcript;
      }
      onText((finalText + interim).trim());
    };
    rec.onerror = (event) => setNote(event.error ?? "speech recognition failed");
    rec.onend = () => {
      setListening(false);
      recognition.current = null;
      if (finalText.trim()) onFinal(finalText.trim());
    };
    recognition.current = rec;
    setListening(true);
    rec.start();
  }

  return (
    <>
      <Pressable
        style={[styles.button, listening && styles.buttonPrimary, disabled && { opacity: 0.5 }]}
        disabled={disabled}
        onPress={() => (listening ? recognition.current?.stop() : start())}
      >
        <Text style={styles.buttonText}>{listening ? "● Listening…" : "🎤 Speak"}</Text>
      </Pressable>
      {note && <Text style={[styles.muted, { color: colors.yellow }]}>{note}</Text>}
    </>
  );
}
