/**
 * Sova's default mobile theme: near-black modelling space with a printed-orange accent.
 * Keep semantic colours (success/error/XYZ axes) distinct from the brand accent. A warm
 * cream/green preset is intentionally deferred until it has its own complete visual pass.
 */
import { StyleSheet } from "react-native";

export const colors = {
  bg: "#0b0c0e",
  panel: "#141517",
  panel2: "#1c1d20",
  border: "#303033",
  text: "#f5f2ed",
  muted: "#aaa49d",
  accent: "#ff6b1a",
  accent2: "#e9540b",
  accentWash: "rgba(255,107,26,0.10)",
  accentWashStrong: "rgba(255,107,26,0.17)",
  green: "#35c48d",
  yellow: "#e6b84a",
  red: "#ef5d5d",
  viewport: "#070809",
  selection: "#ff8a42",
  topologyEdge: "#ff9a5c",
  topologyVertex: "#fff1e8",
  symmetryX: "#ff5d6c",
  symmetryY: "#52d273",
  symmetryZ: "#5b9cff",
};

export const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, gap: 12 },
  card: {
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 16,
    padding: 16,
    gap: 10,
  },
  title: { color: colors.text, fontSize: 21, fontWeight: "800", letterSpacing: -0.4 },
  heading: { color: colors.text, fontSize: 15, fontWeight: "700", letterSpacing: -0.1 },
  text: { color: colors.text, fontSize: 14 },
  muted: { color: colors.muted, fontSize: 13 },
  mono: { color: colors.text, fontFamily: "monospace", fontSize: 12 },
  input: {
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    color: colors.text,
    paddingHorizontal: 10,
    paddingVertical: 10,
  },
  button: {
    backgroundColor: colors.panel2,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 11,
    alignItems: "center",
  },
  buttonPrimary: { backgroundColor: colors.accent, borderColor: colors.accent },
  buttonText: { color: colors.text, fontWeight: "600" },
  row: { flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" },
  chip: {
    backgroundColor: colors.panel2,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 9,
    paddingVertical: 4,
  },
  chipText: { color: colors.text, fontSize: 12 },
  error: { color: colors.red, fontSize: 13 },
});
