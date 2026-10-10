/**
 * Scan capture (T-073, T-075, F-002).
 *
 * Plain photos through expo-camera, so this whole screen runs in Expo Go. The guidance is
 * honest about what it can measure without a depth sensor: how many frames arrived, how far
 * around the object the phone has travelled (device motion), and whether the shot was steady.
 * Depth capture (T-076/T-077) is a separate, development-build-only path; when it is
 * unavailable the screen says so instead of pretending.
 */
import { CameraView, useCameraPermissions } from "expo-camera";
import * as ImagePicker from "expo-image-picker";
import { useLocalSearchParams, useRouter } from "expo-router";
import {
  RoomCaptureView,
  type CaptureFinishEvent,
  type InstructionEvent,
  type RoomPlanCapture as NativeRoomPlanCapture,
  type RoomUpdateEvent,
} from "expo-room-plan";
import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  emptyExteriorSectionCounts,
  exteriorCoveragePercent,
  EXTERIOR_SECTIONS,
  normalizeExteriorSectionCounts,
  uncoveredExteriorSections,
  type ExteriorSectionCounts,
  type ExteriorSectionId,
  frameMessage,
  frameProgress,
  guidedTurntableAngle,
} from "@physical-ai/contracts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { probe } from "@/src/capabilities";
import { CoverageRing } from "@/src/CoverageRing";
import { type CaptureHint, ScanTracker, uploadRoomCapture } from "@/src/scan";
import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

/** services/api/app/services/scanning.py: MIN_FRAMES. A hint must never promise more or less. */
const MIN_FRAMES = 12;

type ScanSubject = "object" | "room" | "home" | "exterior";
type ObjectCaptureMode = "walkaround" | "turntable";

const SUBJECTS: { id: ScanSubject; title: string; note: string; target: number }[] = [
  { id: "object", title: "Предмет", note: "Обойдите предмет со всех сторон.", target: 24 },
  { id: "room", title: "Комната / интерьер", note: "Снимайте стены, пол, потолок, двери и окна.", target: 36 },
  { id: "home", title: "Дом · по комнатам", note: "Снимите одну комнату, сохраните её и начните следующую.", target: 36 },
  { id: "exterior", title: "Здание · снаружи", note: "Обойдите фасады перекрывающимися проходами; снимайте крышу только с безопасной точки.", target: 48 },
];

/**
 * RoomPlan reports its own live guidance (`RoomCaptureSession.Instruction`) through
 * `onInstruction`; the native side only forwards the enum case name (see
 * ExpoRoomPlanView.swift), wording stays here so copy changes never need a rebuild.
 * Cases confirmed against Apple's RoomPlan API; anything RoomPlan adds later that isn't
 * in this map still gets an honest generic hint instead of a blank line.
 */
const ROOM_INSTRUCTIONS_RU: Record<string, string> = {
  moveCloseToWall: "Подойдите ближе к стене",
  moveAwayFromWall: "Отойдите дальше от стены",
  slowDown: "Двигайте телефон медленнее",
  turnOnLight: "Включите свет — слишком темно для скана",
  lowTexture: "Наведите камеру на более детализированную часть комнаты",
  normal: "Медленно обводите камерой стены, пол и потолок",
};

function roomInstructionText(instruction: string | null): string {
  if (!instruction) return "Наведите камеру и начните скан";
  return ROOM_INSTRUCTIONS_RU[instruction] ?? "Продолжайте медленно сканировать комнату";
}

/**
 * One finished RoomPlan session, held locally until the user decides to keep it (T-237 UX).
 * `walls/openings/objects` are RoomPlan's own counts (`RoomUpdateEvent`); `roomPlan` is the
 * metric X/Z wall/opening projection that is validated into a server-side floor plan.
 */
interface CapturedRoomEntry {
  id: string;
  name: string;
  usdzPath: string;
  walls: number;
  openings: number;
  objects: number;
  roomPlan: NativeRoomPlanCapture | null;
}

export default function ScanScreen() {
  const router = useRouter();
  const { projectId, subject: requestedSubject } = useLocalSearchParams<{ projectId?: string; subject?: string }>();
  const { session, client } = useSession();
  const capabilities = probe();

  const camera = useRef<CameraView>(null);
  const tracker = useRef(new ScanTracker());
  const [permission, requestPermission] = useCameraPermissions();
  const [scanId, setScanId] = useState<string | null>(null);
  const [subject, setSubject] = useState<ScanSubject | null>(
    requestedSubject === "room" || requestedSubject === "home" || requestedSubject === "exterior"
      ? requestedSubject
      : requestedSubject === "object"
        ? "object"
        : null,
  );
  const [frames, setFrames] = useState(0);
  const [objectCaptureMode, setObjectCaptureMode] = useState<ObjectCaptureMode | null>(null);
  const [hint, setHint] = useState<CaptureHint>({ level: "info", message: "Медленно обойдите объект съёмки." });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chosen = SUBJECTS.find((entry) => entry.id === subject);
  // the API refuses fewer than 12 frames; the bar ends at the recommended count for the subject
  const frameLimits = { minFrames: MIN_FRAMES, maxFrames: Math.max(chosen?.target ?? 24, MIN_FRAMES + 1) };
  const progress = frameProgress(frames, frameLimits);

  // T-196: RoomPlan only makes sense at room scale, and only when the platform says a
  // LiDAR sensor is actually behind it (see src/capabilities.ts — never assumed true).
  const canUseLidar = (subject === "room" || subject === "home") && capabilities.depthScan;
  const [mode, setMode] = useState<"photo" | "lidar" | null>(null);
  const [roomProgress, setRoomProgress] = useState<RoomUpdateEvent | null>(null);
  const [capturingRoom, setCapturingRoom] = useState(false);
  const [roomBusy, setRoomBusy] = useState(false);
  const [roomInstruction, setRoomInstruction] = useState<string | null>(null);
  const [roomStage, setRoomStage] = useState<"capture" | "roomDone" | "picker">("capture");
  const [capturedRooms, setCapturedRooms] = useState<CapturedRoomEntry[]>([]);
  const [selectedRooms, setSelectedRooms] = useState<Set<string>>(new Set());
  const [lastRoom, setLastRoom] = useState<CapturedRoomEntry | null>(null);
  const [exteriorCounts, setExteriorCounts] = useState<ExteriorSectionCounts>(emptyExteriorSectionCounts);
  const [exteriorSection, setExteriorSection] = useState<ExteriorSectionId>("front");
  const [roofSkipped, setRoofSkipped] = useState(false);
  const [knownSpanMm, setKnownSpanMm] = useState("");
  const [resuming, setResuming] = useState(false);
  const isExterior = subject === "exterior";
  const isObjectSubject = subject === "object";
  const isTurntable = isObjectSubject && objectCaptureMode === "turntable";
  const turntableAngle = guidedTurntableAngle(frames, chosen?.target ?? 24);
  // Recomputed only when a frame lands — azimuth drifts constantly, but "covered" should
  // mean a captured frame exists in that direction, not merely pointing at it.
  const objectCoverage = useMemo(
    () => (isObjectSubject ? tracker.current.sectorCoverage(12) : null),
    [isObjectSubject, frames],
  );
  const uncoveredExterior = uncoveredExteriorSections(exteriorCounts);
  const exteriorCoverage = exteriorCoveragePercent(exteriorCounts);
  const scaleMm = Number(knownSpanMm.replace(",", "."));
  const exteriorScaleValid = Number.isFinite(scaleMm) && scaleMm > 0 && scaleMm <= 1_000_000;
  const exteriorResumeKey = session ? `sova:exterior-scan:${session.workspaceId}` : null;

  useEffect(() => {
    const stop = tracker.current.watchMotion(setHint);
    return stop;
  }, []);

  useEffect(() => {
    if (subject && !canUseLidar) setMode("photo"); // nothing to choose: object, or no LiDAR
  }, [subject, canUseLidar]);

  useEffect(() => {
    if (!isExterior || !client || !exteriorResumeKey || scanId) return;
    let cancelled = false;
    setResuming(true);
    void (async () => {
      try {
        const savedId = await AsyncStorage.getItem(exteriorResumeKey);
        if (!savedId || cancelled) return;
        const saved = await client.getScan(savedId);
        if (saved.status !== "capturing" && saved.status !== "uploading") {
          await AsyncStorage.removeItem(exteriorResumeKey);
          return;
        }
        const savedFrames = await client.listScanFrames(savedId);
        const details = saved.capture_stats.exterior as Record<string, unknown> | undefined;
        const counts = normalizeExteriorSectionCounts(details?.section_counts);
        const frameCounts = emptyExteriorSectionCounts();
        for (const frame of savedFrames) {
          const frameSection = frame.pose.exterior_section;
          if (typeof frameSection === "string" && EXTERIOR_SECTIONS.some((entry) => entry.id === frameSection)) {
            frameCounts[frameSection as ExteriorSectionId] += 1;
          }
        }
        for (const entry of EXTERIOR_SECTIONS) {
          counts[entry.id] = Math.max(counts[entry.id], frameCounts[entry.id]);
        }
        const current = details?.current_section;
        tracker.current.restore(savedFrames);
        if (cancelled) return;
        setScanId(savedId);
        setFrames(savedFrames.filter((frame) => frame.kind === "rgb").length);
        setExteriorCounts(counts);
        if (typeof current === "string" && EXTERIOR_SECTIONS.some((entry) => entry.id === current)) {
          setExteriorSection(current as ExteriorSectionId);
        }
        setRoofSkipped(details?.roof_skipped === true);
        if (details?.known_span_mm != null) setKnownSpanMm(String(details.known_span_mm));
        setHint({ level: "good", message: "Незавершённый наружный скан восстановлен." });
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setResuming(false);
      }
    })();
    return () => { cancelled = true; };
  }, [client, exteriorResumeKey, isExterior, scanId]);

  function exteriorStats(
    counts: ExteriorSectionCounts,
    paused: boolean,
    currentSection: ExteriorSectionId = exteriorSection,
  ) {
    return {
      ...tracker.current.stats(),
      exterior: {
        section_counts: counts,
        current_section: currentSection,
        uncovered_sections: uncoveredExteriorSections(counts).map((entry) => entry.id),
        coverage_pct: exteriorCoveragePercent(counts),
        roof_skipped: roofSkipped,
        known_span_mm: exteriorScaleValid ? scaleMm : null,
        paused,
        gps_role: "metadata_only",
      },
    };
  }

  const start = useCallback(async () => {
    if (!client || !session || scanId) return;
    const scan = await client.createScan({
      workspace_id: session.workspaceId,
      project_id: projectId ?? null,
      mode: "rgb",
      label: `${chosen?.title ?? "Предмет"} · скан с телефона`,
      capabilities: {
        runtime: capabilities.runtime,
        depth_scan: false,
        native_depth_module_available: capabilities.depthScan,
        subject: subject ?? "object",
        stylus: capabilities.stylus,
        ...(isExterior
          ? {
              capture_plan: "facade_sections_v1",
              camera_pose: "device_motion_orientation",
              metric_scale: "none",
              gps_role: "metadata_only",
              roomplan_used: false,
            }
          : isObjectSubject
            ? {
                capture_plan: isTurntable ? "guided_turntable_v1" : "walkaround_azimuth_v1",
                camera_pose: isTurntable ? "user_confirmed_turntable_angle" : "device_motion_orientation",
                turntable: isTurntable,
              }
            : {}),
      },
    });
    setScanId(scan.id);
    if (isExterior && exteriorResumeKey) {
      await AsyncStorage.setItem(exteriorResumeKey, scan.id);
      await client.updateCaptureStats(scan.id, exteriorStats(exteriorCounts, false));
    }
    return scan.id;
  }, [capabilities, chosen, client, exteriorCounts, exteriorResumeKey, isExterior, isObjectSubject, isTurntable, projectId, roofSkipped, scanId, session, subject, knownSpanMm, exteriorSection]);

  /** Pictures already on the phone become frames of this scan (no camera pose is claimed for them). */
  async function addFromLibrary() {
    if (!client || busy || isExterior) return;
    setBusy(true);
    setError(null);
    try {
      const id = scanId ?? (await start());
      if (!id) return;
      const picked = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        allowsMultipleSelection: true,
        selectionLimit: Math.max(frameLimits.maxFrames - frames, 1),
        quality: 0.8,
        exif: false,
      });
      if (picked.canceled) return;
      let count = frames;
      for (const asset of picked.assets) {
        const frame = await tracker.current.upload(client, id, asset.uri, { fromLibrary: true, depthAvailable: false });
        count = frame.sequence_no + 1;
        setFrames(count);
      }
      setHint({ level: "info", message: `Добавлено из галереи: ${picked.assets.length}. Всего кадров: ${count}.` });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function capture() {
    if (!client || busy) return;
    setBusy(true);
    setError(null);
    try {
      const id = scanId ?? (await start());
      if (!id) return;
      const photo = await camera.current?.takePictureAsync({ quality: 0.7, skipProcessing: true });
      if (!photo?.uri) throw new Error("the camera returned no image");
      const frame = await tracker.current.upload(
        client,
        id,
        photo.uri,
        isExterior
          ? { exteriorSection, depthAvailable: false }
          : isTurntable
            ? {
                depthAvailable: false,
                azimuthOverrideDeg: turntableAngle,
                poseSource: "guided_turntable_step",
              }
            : { depthAvailable: false },
      );
      setFrames(frame.sequence_no + 1);
      if (isExterior) {
        const nextCounts = {
          ...exteriorCounts,
          [exteriorSection]: exteriorCounts[exteriorSection] + 1,
        };
        setExteriorCounts(nextCounts);
        const current = EXTERIOR_SECTIONS.find((entry) => entry.id === exteriorSection);
        const next = uncoveredExteriorSections(nextCounts)[0];
        const nextSection = current && nextCounts[exteriorSection] >= current.targetFrames && next
          ? next.id
          : exteriorSection;
        if (current && nextCounts[exteriorSection] >= current.targetFrames && next) {
          setExteriorSection(nextSection);
          setHint({ level: "good", message: `${current.titleRu} покрыт. Дальше: ${next.titleRu}.` });
        } else if (!next) {
          setHint({ level: "good", message: "Все четыре фасада покрыты. Добавьте крышу только если это безопасно." });
        } else {
          setHint({ level: "info", message: `${current?.titleRu}: ещё ${Math.max(0, (current?.targetFrames ?? 0) - nextCounts[exteriorSection])} кадров с перекрытием.` });
        }
        await client.updateCaptureStats(id, exteriorStats(nextCounts, false, nextSection));
      } else {
        const captured = frame.sequence_no + 1;
        if (isTurntable) {
          const target = chosen?.target ?? 24;
          setHint(
            captured >= target
              ? { level: "good", message: "Полный оборот снят — можно собирать 3D." }
              : {
                  level: "info",
                  message: `Поверните стол до ${guidedTurntableAngle(captured, target)}° и снимите следующую позицию.`,
                },
          );
        } else {
          setHint(tracker.current.hint(captured, chosen?.target ?? 24));
        }
        await client.updateCaptureStats(id, tracker.current.stats());
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    if (!client || !scanId) return;
    setBusy(true);
    setError(null);
    try {
      if (isExterior) {
        if (uncoveredExterior.length) {
          throw new Error(`Не покрыто: ${uncoveredExterior.map((entry) => entry.titleRu).join(", ")}.`);
        }
        if (!exteriorScaleValid) {
          throw new Error("Укажите измеренную максимальную длину здания или самого длинного фасада.");
        }
        await client.updateCaptureStats(scanId, exteriorStats(exteriorCounts, false));
        await client.finalizeScan(scanId, {
          scale_hint_mm: scaleMm,
          scale_confidence: 0.8,
        });
        if (exteriorResumeKey) await AsyncStorage.removeItem(exteriorResumeKey);
      } else {
        await client.finalizeScan(scanId, tracker.current.scaleHint());
      }
      router.replace(`/scan/${scanId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  async function pauseExterior() {
    if (!client || !scanId || !exteriorResumeKey || busy) return;
    setBusy(true);
    setError(null);
    try {
      await client.updateCaptureStats(scanId, exteriorStats(exteriorCounts, true));
      await AsyncStorage.setItem(exteriorResumeKey, scanId);
      router.back();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  /**
   * One RoomPlan session finished (native side already exported its USDZ to a temp file).
   * Multi-room UX (T-237): hold it locally and let the user decide to scan another room or
   * stop, instead of uploading and navigating away immediately.
   */
  function handleRoomCaptureFinish(event: CaptureFinishEvent) {
    const entry: CapturedRoomEntry = {
      id: `room-${capturedRooms.length + 1}-${Date.now()}`,
      name: `Комната ${capturedRooms.length + 1}`,
      usdzPath: event.usdzPath,
      walls: event.walls,
      openings: event.openings,
      objects: event.objects,
      roomPlan: event.roomPlan ?? null,
    };
    setCapturedRooms((prev) => [...prev, entry]);
    setSelectedRooms((prev) => new Set(prev).add(entry.id));
    setLastRoom(entry);
    setRoomProgress(null);
    setRoomInstruction(null);
    setRoomStage("roomDone");
  }

  /** T-196: `mode: "scanner"` routes this session to the fusion provider — the captured
   * room's own geometry and scale, not a guess (`worker/reconstruction.py::ScaleReport`).
   * Each room becomes its own `Scan`; its metric wall/opening projection is attached before
   * reconstruction so accepting the result creates both the mesh and a versioned 2D plan.
   * Separate RoomPlan sessions still lack a shared coordinate frame, so this does not pretend
   * to merge several rooms into one building plan. */
  async function createAndUploadRoom(entry: CapturedRoomEntry): Promise<string> {
    if (!client || !session) throw new Error("Войдите, чтобы сохранить скан.");
    if (!entry.roomPlan) {
      throw new Error(
        "Текущая development build не передаёт геометрию RoomPlan. Пересоберите iOS-приложение.",
      );
    }
    const scan = await client.createScan({
      workspace_id: session.workspaceId,
      project_id: projectId ?? null,
      mode: "scanner",
      label: `${entry.name} · RoomPlan (LiDAR)`,
      capabilities: {
        runtime: capabilities.runtime,
        depth_scan: true,
        native_depth_module_available: true,
        subject: subject ?? "room",
        stylus: capabilities.stylus,
        capture_source: "apple_roomplan",
      },
    });
    await client.setScanRoomPlan(scan.id, entry.roomPlan);
    await uploadRoomCapture(client, scan.id, session.workspaceId, entry.usdzPath);
    await client.finalizeScan(scan.id, {}); // a device measurement, no size guess to attach
    return scan.id;
  }

  function continueScanningRooms() {
    setRoomProgress(null);
    setRoomInstruction(null);
    setRoomStage("capture");
  }

  function toggleRoomSelected(id: string) {
    setSelectedRooms((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  /** From the single-room "done" screen: one room, nothing to pick between. */
  async function finishSingleRoom(entry: CapturedRoomEntry) {
    setRoomBusy(true);
    setError(null);
    try {
      const id = await createAndUploadRoom(entry);
      router.replace(`/scan/${id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRoomBusy(false);
    }
  }

  /** From the multi-room picker: upload only the rooms the user kept checked. */
  async function finishSelectedRooms() {
    const chosen = capturedRooms.filter((entry) => selectedRooms.has(entry.id));
    if (!chosen.length) {
      setError("Выберите хотя бы одну комнату.");
      return;
    }
    setRoomBusy(true);
    setError(null);
    try {
      let lastId: string | null = null;
      for (const entry of chosen) {
        lastId = await createAndUploadRoom(entry);
      }
      if (projectId) router.replace(`/project/${projectId}`);
      else if (lastId) router.replace(`/scan/${lastId}`);
      else router.replace("/scan");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRoomBusy(false);
    }
  }

  if (!session) {
    return (
      <View style={[styles.screen, styles.content]}>
        <Text style={styles.muted}>Войдите, чтобы начать сканирование.</Text>
      </View>
    );
  }

  if (!subject) {
    return (
      <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
        <Text style={styles.heading}>Что будем сканировать?</Text>
        <Text style={styles.muted}>Выберите предмет, комнату, дом изнутри или здание снаружи. Съёмка начинается только после выбора.</Text>
        {SUBJECTS.map((entry) => (
          <Pressable key={entry.id} style={styles.card} onPress={() => setSubject(entry.id)}>
            <Text style={styles.heading}>{entry.title} →</Text>
            <Text style={styles.muted}>{entry.note}</Text>
          </Pressable>
        ))}
      </ScrollView>
    );
  }

  if (canUseLidar && mode === null) {
    return (
      <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
        <Text style={styles.heading}>Как снимать: {chosen?.title.toLowerCase()}</Text>
        <Pressable style={styles.card} onPress={() => setMode("lidar")}>
          <Text style={styles.heading}>LiDAR (RoomPlan) →</Text>
          <Text style={styles.muted}>
            Реальные размеры и геометрия стен с датчика. Требует iPhone/iPad с LiDAR.
          </Text>
        </Pressable>
        <Pressable style={styles.card} onPress={() => setMode("photo")}>
          <Text style={styles.heading}>Фотокадры →</Text>
          <Text style={styles.muted}>Без датчика глубины; размер — по вашей оценке.</Text>
        </Pressable>
      </ScrollView>
    );
  }

  if (isObjectSubject && objectCaptureMode === null) {
    return (
      <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
        <Text style={styles.heading}>Как снимать предмет?</Text>
        <Pressable style={styles.card} onPress={() => setObjectCaptureMode("walkaround")}>
          <Text style={styles.heading}>Обойти предмет →</Text>
          <Text style={styles.muted}>
            Двигайтесь вокруг неподвижного предмета. Покрытие считается по повороту телефона.
          </Text>
        </Pressable>
        <Pressable style={styles.card} onPress={() => setObjectCaptureMode("turntable")}>
          <Text style={styles.heading}>Поворотный стол →</Text>
          <Text style={styles.muted}>
            Закрепите телефон, поворачивайте предмет по подсказанным углам и снимите 24 позиции полного оборота.
          </Text>
        </Pressable>
      </ScrollView>
    );
  }

  if (mode === "lidar" && roomStage === "roomDone" && lastRoom) {
    return (
      <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
        <View style={styles.card}>
          <Text style={styles.heading}>{lastRoom.name} готова</Text>
          <Text style={styles.muted}>
            Стены: {lastRoom.walls} · проёмы: {lastRoom.openings} · предметы: {lastRoom.objects}
          </Text>
          <Text style={styles.muted}>
            При сохранении метрические стены, двери и окна будут проверены сервером и станут
            редактируемым 2D-планом той же версии проекта.
          </Text>
        </View>
        <View style={styles.card}>
          <Pressable style={[styles.button, styles.buttonPrimary]} onPress={continueScanningRooms}>
            <Text style={styles.buttonText}>Продолжить · отснять ещё комнату</Text>
          </Pressable>
          <Pressable
            style={[styles.button, roomBusy && { opacity: 0.5 }]}
            disabled={roomBusy}
            onPress={() =>
              void (capturedRooms.length > 1 ? setRoomStage("picker") : finishSingleRoom(lastRoom))
            }
          >
            <Text style={styles.buttonText}>{roomBusy ? "Сохраняем…" : "Завершить"}</Text>
          </Pressable>
        </View>
        {error && <Text style={styles.error}>{error}</Text>}
      </ScrollView>
    );
  }

  if (mode === "lidar" && roomStage === "picker") {
    return (
      <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
        <View style={styles.card}>
          <Text style={styles.heading}>Отснятые комнаты · {capturedRooms.length}</Text>
          <Text style={styles.muted}>
            Отметьте, какие комнаты сохранить как отдельные сканы, или отсканируйте ещё одну.
            Объединение в один план дома (T-197) пока не реализовано — каждая комната сохраняется
            отдельным сканом.
          </Text>
        </View>
        <View style={[styles.row, { flexWrap: "wrap" }]}>
          {capturedRooms.map((entry) => {
            const checked = selectedRooms.has(entry.id);
            return (
              <Pressable
                key={entry.id}
                style={[
                  styles.card,
                  { width: "47%" },
                  checked && { borderColor: colors.accent },
                ]}
                onPress={() => toggleRoomSelected(entry.id)}
              >
                <Text style={{ fontSize: 28 }}>📦</Text>
                <Text style={styles.heading}>{entry.name}</Text>
                <Text style={styles.muted}>
                  стены {entry.walls} · проёмы {entry.openings} · предметы {entry.objects}
                </Text>
                <Text style={{ color: checked ? colors.green : colors.muted, fontSize: 12 }}>
                  {checked ? "✓ выбрано" : "нажмите, чтобы выбрать"}
                </Text>
              </Pressable>
            );
          })}
          <Pressable
            style={[styles.card, { width: "47%", alignItems: "center", justifyContent: "center" }]}
            onPress={continueScanningRooms}
          >
            <Text style={[styles.heading, { fontSize: 28 }]}>+</Text>
            <Text style={styles.muted}>Добавить комнату</Text>
          </Pressable>
        </View>
        <View style={styles.card}>
          <Pressable
            style={[
              styles.button,
              styles.buttonPrimary,
              (roomBusy || selectedRooms.size === 0) && { opacity: 0.5 },
            ]}
            disabled={roomBusy || selectedRooms.size === 0}
            onPress={() => void finishSelectedRooms()}
          >
            <Text style={styles.buttonText}>{roomBusy ? "Сохраняем…" : "Готово"}</Text>
          </Pressable>
        </View>
        {error && <Text style={styles.error}>{error}</Text>}
      </ScrollView>
    );
  }

  if (mode === "lidar") {
    return (
      <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
        <View style={styles.card}>
          <Text style={styles.heading}>{chosen?.title} · LiDAR</Text>
          <Text style={styles.muted}>
            Медленно обойдите комнату — стены, проёмы и предметы определяются на лету.
          </Text>
          {capturedRooms.length > 0 && (
            <Text style={styles.muted}>Уже отснято комнат: {capturedRooms.length}.</Text>
          )}
        </View>
        <View style={{ height: 380, borderRadius: 10, overflow: "hidden", position: "relative" }}>
          {RoomCaptureView && (
            <RoomCaptureView
              style={{ flex: 1 }}
              capturing={capturingRoom}
              onRoomUpdate={(e) => setRoomProgress(e.nativeEvent)}
              onInstruction={(e: { nativeEvent: InstructionEvent }) =>
                setRoomInstruction(e.nativeEvent.instruction)
              }
              onCaptureFinish={(e) => {
                setCapturingRoom(false);
                handleRoomCaptureFinish(e.nativeEvent);
              }}
              onCaptureError={(e) => {
                setCapturingRoom(false);
                setError(e.nativeEvent.message);
              }}
            />
          )}
          {capturingRoom && (
            <>
              {/* Polycam-style live badge: RoomPlan's own element counts while capture is active;
                  the metric geometry arrives only in the post-processed finish event. */}
              <View
                style={{
                  position: "absolute",
                  top: 10,
                  left: 10,
                  backgroundColor: "rgba(15,17,21,0.72)",
                  borderRadius: 999,
                  paddingHorizontal: 12,
                  paddingVertical: 6,
                }}
              >
                <Text style={{ color: colors.text, fontWeight: "700", fontSize: 13 }}>
                  {roomProgress
                    ? `стены ${roomProgress.walls} · проёмы ${roomProgress.openings} · предметы ${roomProgress.objects}`
                    : "сканирование начато…"}
                </Text>
              </View>
              {/* Polycam-style bottom guidance, from RoomPlan's own `onInstruction`. */}
              <View
                style={{
                  position: "absolute",
                  left: 10,
                  right: 10,
                  bottom: 10,
                  backgroundColor: "rgba(15,17,21,0.72)",
                  borderRadius: 10,
                  paddingHorizontal: 12,
                  paddingVertical: 8,
                }}
              >
                <Text style={{ color: colors.text, textAlign: "center", fontSize: 13 }}>
                  {roomInstructionText(roomInstruction)}
                </Text>
              </View>
            </>
          )}
        </View>
        <View style={styles.card}>
          {!capturingRoom && (
            <Text style={styles.heading}>{roomInstructionText(null)}</Text>
          )}
          <View style={styles.row}>
            <Pressable
              style={[styles.button, styles.buttonPrimary, roomBusy && { opacity: 0.5 }]}
              disabled={roomBusy}
              onPress={() => setCapturingRoom((v) => !v)}
            >
              <Text style={styles.buttonText}>
                {roomBusy ? "Собираем модель…" : capturingRoom ? "Завершить комнату" : "Начать скан"}
              </Text>
            </Pressable>
            {capturedRooms.length === 0 && (
              <Pressable style={styles.button} disabled={capturingRoom || roomBusy} onPress={() => setMode(null)}>
                <Text style={styles.buttonText}>Сменить режим</Text>
              </Pressable>
            )}
          </View>
          {error && <Text style={styles.error}>{error}</Text>}
        </View>
      </ScrollView>
    );
  }

  if (!permission) return <View style={styles.screen} />;
  if (!permission.granted) {
    return (
      <View style={[styles.screen, styles.content]}>
        <View style={styles.card}>
          <Text style={styles.heading}>Доступ к камере</Text>
          <Text style={styles.muted}>
            Камера нужна для съёмки. Кадры отправляются только после нажатия «Снять кадр».
          </Text>
          <Pressable
            style={[styles.button, styles.buttonPrimary]}
            onPress={() => void requestPermission()}
          >
            <Text style={styles.buttonText}>Разрешить камеру</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  const hintColour =
    hint.level === "warn" ? colors.yellow : hint.level === "good" ? colors.green : colors.muted;

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.card}>
        <Text style={styles.heading}>{chosen?.title}</Text>
        <Text style={styles.muted}>{chosen?.note}</Text>
        {isExterior ? (
          <Text style={styles.muted}>
            Это фотограмметрия фасадов. RoomPlan предназначен только для помещений и здесь не используется.
          </Text>
        ) : !canUseLidar && (
          <Text style={styles.muted}>
            {capabilities.depthScanReason ?? "Сейчас доступна только фотосъёмка; размер — по вашей оценке."}
          </Text>
        )}
        {subject === "home" && <Text style={styles.muted}>Сейчас одна сессия = одна комната. Объединение комнат в план дома появится с нативным сканированием.</Text>}
      </View>
      {isExterior && (
        <View style={styles.card}>
          <Text style={styles.heading}>Покрытие фасадов · {exteriorCoverage}%</Text>
          {resuming && <Text style={styles.muted}>Восстанавливаем незавершённую съёмку…</Text>}
          <View style={styles.row}>
            {EXTERIOR_SECTIONS.map((entry) => (
              <Pressable
                key={entry.id}
                style={[
                  styles.chip,
                  exteriorSection === entry.id && { borderColor: colors.accent, backgroundColor: colors.accent2 },
                ]}
                onPress={() => {
                  setExteriorSection(entry.id);
                  if (entry.id === "roof") setRoofSkipped(false);
                }}
              >
                <Text style={styles.chipText}>
                  {entry.titleRu} · {exteriorCounts[entry.id]}/{entry.targetFrames}
                </Text>
              </Pressable>
            ))}
          </View>
          <Text style={styles.text}>
            {EXTERIOR_SECTIONS.find((entry) => entry.id === exteriorSection)?.guidanceRu}
          </Text>
          <Text style={styles.muted}>
            Не покрыто: {uncoveredExterior.length ? uncoveredExterior.map((entry) => entry.titleRu).join(", ") : "все обязательные фасады сняты"}.
          </Text>
          <Pressable
            style={styles.button}
            onPress={() => {
              setRoofSkipped((value) => !value);
              if (!roofSkipped && exteriorSection === "roof") setExteriorSection("front");
            }}
          >
            <Text style={styles.buttonText}>{roofSkipped ? "Крыша пропущена безопасно ✓" : "Крышу небезопасно снимать — пропустить"}</Text>
          </Pressable>
          <Text style={styles.heading}>Масштаб</Text>
          <Text style={styles.muted}>
            Измерьте максимальную длину здания или самого длинного фасада. GPS сохраняется только как метаданные и не считается точной геометрией.
          </Text>
          <TextInput
            style={styles.input}
            value={knownSpanMm}
            onChangeText={setKnownSpanMm}
            keyboardType="decimal-pad"
            placeholder="Например, 12400 мм"
            placeholderTextColor={colors.muted}
          />
          {knownSpanMm.length > 0 && !exteriorScaleValid && (
            <Text style={styles.error}>Введите положительный размер не больше 1 000 000 мм.</Text>
          )}
        </View>
      )}
      <View style={{ height: 380, borderRadius: 10, overflow: "hidden", position: "relative" }}>
        <CameraView ref={camera} style={{ flex: 1 }} facing="back" />
        {isTurntable && (
          <View
            style={{
              position: "absolute",
              left: 12,
              right: 12,
              bottom: 12,
              paddingHorizontal: 14,
              paddingVertical: 10,
              borderRadius: 12,
              backgroundColor: "rgba(15,17,21,0.78)",
            }}
          >
            <Text style={{ color: colors.text, textAlign: "center", fontWeight: "700" }}>
              Позиция {Math.min(frames + 1, chosen?.target ?? 24)} из {chosen?.target ?? 24} · {turntableAngle}°
            </Text>
            <Text style={{ color: colors.muted, textAlign: "center", fontSize: 12 }}>
              Телефон не двигайте; поверните только стол до указанной отметки.
            </Text>
          </View>
        )}
      </View>

      <View style={styles.card}>
        <Text style={styles.heading}>
          {isExterior ? `${frames} кадров · покрытие ${exteriorCoverage}%` : `${frames} / ${chosen?.target ?? 24} кадров`}
        </Text>
        {isObjectSubject && objectCoverage && (
          <View style={[styles.row, { alignItems: "center", gap: 12 }]} accessibilityLabel={`Покрыто секторов: ${objectCoverage.coveredSectors} из ${objectCoverage.sectorCount}`}>
            <CoverageRing covered={objectCoverage.covered} size={92} />
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.text}>Обход вокруг объекта: {objectCoverage.coveragePercent}%</Text>
              <Text style={styles.muted}>
                {isTurntable
                  ? "Оранжевый сектор — подтверждённая позиция стола. Это заданный угол, не измеренная 3D-поза камеры."
                  : "Оранжевый сектор — оттуда уже есть кадр. Это грубая оценка по повороту телефона, не точная 3D-поза."}
              </Text>
            </View>
          </View>
        )}
        {!isExterior && (
          <View accessibilityLabel={frameMessage(progress, frameLimits, "ru")}>
            <View style={{ height: 8, borderRadius: 4, backgroundColor: colors.panel2, overflow: "hidden" }}>
              <View
                style={{
                  width: `${Math.round(progress.fraction * 100)}%`,
                  height: 8,
                  backgroundColor: progress.canProcess ? colors.green : colors.yellow,
                }}
              />
              <View
                style={{
                  position: "absolute",
                  left: `${Math.round(progress.minimumMark * 100)}%`,
                  width: 2,
                  height: 8,
                  backgroundColor: colors.text,
                }}
              />
            </View>
            <View style={[styles.row, { justifyContent: "space-between", marginTop: 4 }]}>
              <Text style={styles.muted}>{frameMessage(progress, frameLimits, "ru")}</Text>
              <Text style={styles.muted}>мин {frameLimits.minFrames} · рек. {frameLimits.maxFrames}</Text>
            </View>
          </View>
        )}
        {!isExterior && frames < frameLimits.maxFrames && (
          <Text style={styles.muted}>
            Добавьте ещё один ракурс для более точного результата — разные углы помогают вплоть до рекомендованного числа кадров.
          </Text>
        )}
        <Text style={[styles.text, { color: hintColour }]}>{hint.message}</Text>
        {!isExterior && !capabilities.depthScan && <Text style={styles.muted}>{capabilities.depthScanReason}</Text>}
        <View style={styles.row}>
          <Pressable
            style={[styles.button, styles.buttonPrimary, busy && { opacity: 0.5 }]}
            disabled={busy}
            onPress={capture}
          >
            <Text style={styles.buttonText}>
              {busy ? "Сохраняем…" : isTurntable ? `Снять ${turntableAngle}°` : "Снять кадр"}
            </Text>
          </Pressable>
          {!isExterior && (
            <Pressable
              style={[styles.button, busy && { opacity: 0.5 }]}
              disabled={busy}
              onPress={() => void addFromLibrary()}
            >
              <Text style={styles.buttonText}>Из галереи</Text>
            </Pressable>
          )}
          {isExterior && scanId && (
            <Pressable
              style={[styles.button, busy && { opacity: 0.5 }]}
              disabled={busy}
              onPress={() => void pauseExterior()}
            >
              <Text style={styles.buttonText}>Пауза</Text>
            </Pressable>
          )}
          <Pressable
            style={[
              styles.button,
              (busy || !progress.canProcess || (isExterior && (uncoveredExterior.length > 0 || !exteriorScaleValid))) && { opacity: 0.5 },
            ]}
            disabled={busy || !progress.canProcess || (isExterior && (uncoveredExterior.length > 0 || !exteriorScaleValid))}
            onPress={finish}
          >
            <Text style={styles.buttonText}>Собрать 3D</Text>
          </Pressable>
        </View>
        {frames > 0 && !progress.canProcess && (
          <Text style={styles.muted}>Для сборки нужно минимум {frameLimits.minFrames} кадров.</Text>
        )}
        {isExterior && uncoveredExterior.length > 0 && (
          <Text style={styles.muted}>Перед сборкой закройте все четыре направления фасадов.</Text>
        )}
        {isExterior && !exteriorScaleValid && (
          <Text style={styles.muted}>Для метрической модели нужен измеренный максимальный размер.</Text>
        )}
        {error && <Text style={styles.error}>{error}</Text>}
      </View>
    </ScrollView>
  );
}
