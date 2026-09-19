"use client";

/**
 * Voice modelling (T-132, F-017): say it instead of typing it.
 *
 * The browser's own speech recognition (Web Speech API) fills the prompt as you speak; the
 * words go down the same path as typed ones — the planner, the validator, the kernel — so
 * a voice command can create a part, change it, or roll it back exactly like text. Where
 * the browser has no recognition (Firefox, some WebViews) the button says so instead of
 * pretending.
 */
import { useEffect, useRef, useState } from "react";

// The Web Speech API is not in lib.dom for every TS target; the shape we use is small.
interface RecognitionResultLike {
  isFinal: boolean;
  0: { transcript: string };
}
interface RecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<RecognitionResultLike>;
}
interface RecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  onresult: ((event: RecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => RecognitionLike;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export interface VoiceButtonProps {
  /** Every partial transcript, so the prompt fills as the user speaks. */
  onText: (text: string) => void;
  /** The final transcript; with hands-free on, the caller sends it. */
  onFinal: (text: string) => void;
  language: "ru" | "en";
  disabled?: boolean;
}

export function VoiceButton({ onText, onFinal, language, disabled }: VoiceButtonProps) {
  const [supported, setSupported] = useState<boolean | null>(null);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recognition = useRef<RecognitionLike | null>(null);

  useEffect(() => {
    setSupported(recognitionCtor() !== null);
    return () => recognition.current?.abort();
  }, []);

  function start() {
    const Ctor = recognitionCtor();
    if (!Ctor) return;
    setError(null);
    const rec = new Ctor();
    rec.lang = language === "ru" ? "ru-RU" : "en-US";
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;
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
    rec.onerror = (event) => {
      setError(
        event.error === "not-allowed"
          ? "microphone access was refused"
          : event.error === "no-speech"
            ? "heard nothing"
            : (event.error ?? "speech recognition failed"),
      );
    };
    rec.onend = () => {
      setListening(false);
      recognition.current = null;
      if (finalText.trim()) onFinal(finalText.trim());
    };
    recognition.current = rec;
    setListening(true);
    rec.start();
  }

  function stop() {
    recognition.current?.stop();
  }

  if (supported === false) {
    return (
      <span className="muted" title="Web Speech API is not available in this browser">
        voice: not in this browser
      </span>
    );
  }
  return (
    <span className="row" style={{ gap: 6 }}>
      <button
        type="button"
        className={`btn ${listening ? "primary" : ""}`}
        disabled={disabled || supported === null}
        onClick={() => (listening ? stop() : start())}
        title={listening ? "Stop listening" : "Say what you want (RU or EN)"}
        aria-pressed={listening}
      >
        {listening ? "● Listening…" : "🎤 Speak"}
      </button>
      {error && <span className="muted">{error}</span>}
    </span>
  );
}
