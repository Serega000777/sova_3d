/** Reference 66: exact fastener envelope -> one exact planar hole -> measured immutable assembly. */
import type {
  FastenerCatalogItem,
  FitTestReport,
  OperationStack,
  PhysicalAiClient,
} from "@physical-ai/contracts";
import { useEffect, useMemo, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { SheetShell } from "./SheetShell";
import { colors, radii, styles } from "./theme";

type Hole = {
  id: string;
  diameterMm: number;
  depthMm: number | null;
  positionMm: number[];
  faceAxis: "x" | "y" | "z";
  faceSign: "+" | "-";
};

const LENGTHS = [6, 8, 10, 12, 16, 20, 25, 30];
const HEADS = ["socket_cap", "pan", "countersunk"] as const;
const DRIVES = ["hex", "phillips", "torx"] as const;

function exactPlanarHoles(stack: OperationStack): Hole[] {
  return stack.operations.flatMap((operation) => {
    const params = operation.params as Record<string, unknown>;
    const face = params.face as Record<string, unknown> | undefined;
    const position = params.position_mm;
    const diameter = Number(params.diameter_mm);
    const depth = params.depth_mm === null || params.depth_mm === undefined
      ? null
      : Number(params.depth_mm);
    if (
      !operation.enabled ||
      operation.type !== "add_hole" ||
      face?.kind !== "face_by_normal" ||
      !["x", "y", "z"].includes(String(face.axis)) ||
      !["+", "-"].includes(String(face.sign)) ||
      !Array.isArray(position) ||
      position.length !== 2 ||
      !position.every((value) => Number.isFinite(Number(value))) ||
      !Number.isFinite(diameter) ||
      diameter <= 0
    ) return [];
    return [{
      id: operation.id,
      diameterMm: diameter,
      depthMm: depth,
      positionMm: position.map(Number),
      faceAxis: face.axis as Hole["faceAxis"],
      faceSign: face.sign as Hole["faceSign"],
    }];
  });
}

export function FastenerSheet({
  visible,
  language,
  client,
  workspaceId,
  versionId,
  onClose,
  onCreatedAssembly,
}: {
  visible: boolean;
  language: "ru" | "en";
  client: PhysicalAiClient | null;
  workspaceId: string | null;
  versionId: string | null;
  onClose: () => void;
  onCreatedAssembly: (versionId: string) => Promise<void>;
}) {
  const ru = language === "ru";
  const [catalog, setCatalog] = useState<FastenerCatalogItem[]>([]);
  const [holes, setHoles] = useState<Hole[]>([]);
  const [size, setSize] = useState("M3");
  const [lengthMm, setLengthMm] = useState(12);
  const [head, setHead] = useState<(typeof HEADS)[number]>("socket_cap");
  const [drive, setDrive] = useState<(typeof DRIVES)[number]>("hex");
  const [holeId, setHoleId] = useState("");
  const [report, setReport] = useState<FitTestReport | null>(null);
  const [fitTestId, setFitTestId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!visible || !client || !versionId) return;
    let cancelled = false;
    setReport(null);
    setFitTestId(null);
    setError(null);
    void Promise.all([client.listFasteners(), client.getOperationStack(versionId)])
      .then(([items, stack]) => {
        if (cancelled) return;
        const found = exactPlanarHoles(stack);
        setCatalog(items);
        setHoles(found);
        setSize((current) => items.some((item) => item.size === current) ? current : items[0]?.size ?? "M3");
        setHoleId((current) => found.some((hole) => hole.id === current) ? current : found[0]?.id ?? "");
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => { cancelled = true; };
  }, [visible, client, versionId]);

  const selected = useMemo(() => catalog.find((item) => item.size === size) ?? null, [catalog, size]);
  const selectedHole = holes.find((hole) => hole.id === holeId) ?? null;

  async function buildAndCheck() {
    if (!client || !workspaceId || !versionId || !selectedHole) return;
    setBusy(true);
    setError(null);
    setReport(null);
    setFitTestId(null);
    try {
      const created = await client.createFastener({
        workspace_id: workspaceId,
        size,
        length_mm: lengthMm,
        head,
        drive,
        label: `Fastener ${size}×${lengthMm}`,
      });
      const built = await client.waitForJob(created.job.job_id, { timeoutMs: 8 * 60_000 });
      if (built.status !== "succeeded") {
        throw new Error(
          (built.error as { message?: string } | null)?.message ??
          (ru ? "Крепёж не построен." : "The fastener could not be built."),
        );
      }
      const fastenerVersionId = (built.result as { version_id?: string } | null)?.version_id;
      if (!fastenerVersionId) throw new Error(ru ? "Сервер не вернул версию крепежа." : "No fastener version returned.");
      const accepted = await client.startFastenerFit(versionId, {
        fastener_version_id: fastenerVersionId,
        hole_operation_id: selectedHole.id,
        wanted: "clearance",
        language,
      });
      const measured = await client.waitForJob(accepted.job_id, { timeoutMs: 8 * 60_000 });
      if (measured.status !== "succeeded") {
        throw new Error(
          (measured.error as { message?: string } | null)?.message ??
          (ru ? "Посадка не измерена." : "The fit could not be measured."),
        );
      }
      const result = measured.result as { fit_test_id?: string; report?: FitTestReport } | null;
      if (!result?.fit_test_id || !result.report?.fastener) {
        throw new Error(ru ? "Сервер вернул неполный отчёт крепежа." : "The fastener report is incomplete.");
      }
      setFitTestId(result.fit_test_id);
      setReport(result.report);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  const result = report?.fastener;
  const compatible = Boolean(result?.geometry_compatible);

  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent="94%"
      tabletWidth={680}
      accessibilityLabel={ru ? "Закрыть точный крепёж" : "Close exact fastener"}
      contentGap={12}
    >
      <View style={{ flexDirection: "row", gap: 12, alignItems: "flex-start" }}>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.title}>{ru ? "Точный крепёж" : "Exact fastener"}</Text>
          <Text style={styles.sectionSubtitle}>
            {ru
              ? "Создаёт отдельное CAD‑тело, ставит его в выбранное точное отверстие и измеряет посадку сервером."
              : "Creates a separate CAD solid, places it in one exact hole, and measures the fit on the server."}
          </Text>
        </View>
        <Pressable accessibilityLabel={ru ? "Закрыть" : "Close"} hitSlop={12} onPress={onClose}>
          <Text style={[styles.sectionTitle, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={{ gap: 14 }} showsVerticalScrollIndicator={false}>
        {holes.length ? (
          <>
            <View style={{ gap: 8 }}>
              <Text style={styles.heading}>{ru ? "Точное отверстие" : "Exact hole"}</Text>
              {holes.map((hole) => (
                <Pressable
                  key={hole.id}
                  accessibilityRole="radio"
                  accessibilityState={{ checked: hole.id === holeId }}
                  onPress={() => { setHoleId(hole.id); setReport(null); }}
                  style={[styles.button, hole.id === holeId && { borderColor: colors.accent, backgroundColor: colors.accentWash }]}
                >
                  <Text style={styles.buttonText}>
                    {hole.id} · {hole.faceSign}{hole.faceAxis.toUpperCase()} · Ø{hole.diameterMm} {ru ? "мм" : "mm"} · {ru ? "позиция" : "position"} {hole.positionMm.join(" × ")}
                  </Text>
                </Pressable>
              ))}
            </View>

            <View style={{ gap: 8 }}>
              <Text style={styles.heading}>{ru ? "Размер" : "Size"}</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 7 }}>
                {catalog.map((item) => (
                  <Pressable
                    key={item.size}
                    accessibilityRole="radio"
                    accessibilityState={{ checked: item.size === size }}
                    onPress={() => { setSize(item.size); setReport(null); }}
                    style={[styles.chip, item.size === size && { borderColor: colors.selection, backgroundColor: colors.accentWash }]}
                  >
                    <Text style={styles.chipText}>{item.size}</Text>
                  </Pressable>
                ))}
              </View>
              {selected && <Text style={styles.muted}>{ru ? "Номинал" : "Nominal"} Ø{selected.nominal_mm} · {ru ? "проходное" : "clearance"} Ø{selected.clearance_mm} {ru ? "мм" : "mm"}</Text>}
            </View>

            <View style={{ gap: 8 }}>
              <Text style={styles.heading}>{ru ? "Длина стержня, мм" : "Shank length, mm"}</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 7 }}>
                {LENGTHS.map((value) => (
                  <Pressable key={value} onPress={() => { setLengthMm(value); setReport(null); }} style={[styles.chip, value === lengthMm && { borderColor: colors.selection, backgroundColor: colors.accentWash }]}>
                    <Text style={styles.chipText}>{value}</Text>
                  </Pressable>
                ))}
              </View>
              <TextInput
                accessibilityLabel={ru ? "Длина крепежа" : "Fastener length"}
                style={styles.input}
                keyboardType="decimal-pad"
                value={String(lengthMm)}
                onChangeText={(value) => { setLengthMm(Number(value.replace(",", "."))); setReport(null); }}
              />
            </View>

            <View style={{ gap: 8 }}>
              <Text style={styles.heading}>{ru ? "Головка" : "Head"}</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 7 }}>
                {HEADS.map((value) => (
                  <Pressable key={value} onPress={() => { setHead(value); setReport(null); }} style={[styles.chip, value === head && { borderColor: colors.selection, backgroundColor: colors.accentWash }]}>
                    <Text style={styles.chipText}>{value.replace("_", " ")}</Text>
                  </Pressable>
                ))}
              </View>
              <Text style={styles.heading}>{ru ? "Шлиц (метаданные)" : "Drive (metadata)"}</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 7 }}>
                {DRIVES.map((value) => (
                  <Pressable key={value} onPress={() => { setDrive(value); setReport(null); }} style={[styles.chip, value === drive && { borderColor: colors.selection, backgroundColor: colors.accentWash }]}>
                    <Text style={styles.chipText}>{value}</Text>
                  </Pressable>
                ))}
              </View>
            </View>

            <Pressable
              disabled={busy || !selectedHole || !Number.isFinite(lengthMm) || lengthMm < 2 || lengthMm > 200}
              onPress={() => void buildAndCheck()}
              style={[styles.button, styles.buttonPrimary, { minHeight: 52 }, busy && { opacity: 0.48 }]}
            >
              <Text style={styles.buttonText}>{busy ? (ru ? "Строим и измеряем…" : "Building and measuring…") : (ru ? "Проверить посадку" : "Check fit")}</Text>
            </Pressable>
          </>
        ) : (
          <View style={[styles.card, { borderColor: colors.yellow }]}>
            <Text style={styles.heading}>{ru ? "Нет поддерживаемого отверстия" : "No supported hole"}</Text>
            <Text style={styles.muted}>
              {ru
                ? "Нужна активная точная CAD‑операция add_hole на плоской грани ±X/±Y/±Z. Отверстия импортированной сетки не угадываются."
                : "An active exact-CAD add_hole on a flat ±X/±Y/±Z face is required. Imported mesh holes are not guessed."}
            </Text>
          </View>
        )}

        {error && <Text style={[styles.muted, { color: colors.red }]}>{error}</Text>}

        {result && (
          <View style={{ gap: 9, padding: 13, borderRadius: radii.section, borderWidth: 1, borderColor: compatible ? colors.green : colors.red, backgroundColor: colors.panel2 }}>
            <Text style={[styles.heading, { color: compatible ? colors.green : colors.red }]}>
              {compatible ? (ru ? "Геометрическая посадка подходит" : "Geometric fit accepted") : (ru ? "Посадка не подходит" : "Fit rejected")}
            </Text>
            <Text style={styles.text}>{result.fastener.size}×{result.fastener.length_mm} · {result.fastener.head.replace("_", " ")} · {result.fastener.drive}</Text>
            <Text style={styles.muted}>{ru ? "Радиальный зазор" : "Radial clearance"}: {result.radial_clearance_mm} {ru ? "мм" : "mm"}</Text>
            <Text style={styles.muted}>{ru ? "Глубина входа" : "Engagement depth"}: {result.engagement_mm} {ru ? "мм" : "mm"} · {ru ? "головка на поверхности" : "head seated"}: {result.head_seated ? (ru ? "да" : "yes") : (ru ? "нет" : "no")}</Text>
            {compatible && fitTestId && (
              <Pressable
                disabled={busy}
                style={[styles.button, styles.buttonPrimary]}
                onPress={() => {
                  if (!client) return;
                  setBusy(true);
                  setError(null);
                  void client.createFitAssembly(fitTestId, `Installed ${result.fastener.size}×${result.fastener.length_mm}`)
                    .then((scene) => onCreatedAssembly(scene.version_id))
                    .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)))
                    .finally(() => setBusy(false));
                }}
              >
                <Text style={styles.buttonText}>{ru ? "Добавить крепёж в модель" : "Add fastener to model"}</Text>
              </Pressable>
            )}
            <Text style={styles.sectionSubtitle}>
              {ru
                ? "Стержень — гладкая номинальная оболочка. Резьба, шлиц, момент затяжки, преднатяг и прочность не моделируются."
                : "The shank is a smooth nominal envelope. Threads, drive recess, torque, preload and strength are not modeled."}
            </Text>
          </View>
        )}
      </ScrollView>
    </SheetShell>
  );
}
