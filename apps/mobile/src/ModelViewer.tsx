/**
 * Mobile 3D viewport (T-054, F-058/F-060): expo-gl + three, JS only, so it runs in Expo Go.
 *
 * One finger orbits, two fingers pan and pinch to zoom, a tap selects the body.
 * A stylus (Apple Pencil, S Pen) is its own pointer type: react-native-gesture-handler
 * reports pressure and tilt in `stylusData`, which the HUD shows and the tap uses to
 * select precisely instead of orbiting.
 *
 * In `outline` and `paint` mode the one-pointer drag draws on the model instead of
 * orbiting it (T-105 / T-109): every sample is ray-cast onto the surface, the path is kept
 * in model millimetres and handed over as a region — the same contract the web uses.
 * A painted version arrives as a GLB with vertex colours and is shown as such (F-034).
 */
import {
  type Point2,
  type RegionSelection,
  type Surface,
  dominantAxis,
  pathToRegion,
  planeAxes,
} from "@physical-ai/contracts";
import { GLView, type ExpoWebGLRenderingContext } from "expo-gl";
import { useCallback, useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

import { colors, styles } from "./theme";

export interface Size {
  x: number;
  y: number;
  z: number;
}

export type DrawMode = "orbit" | "outline" | "paint";

export interface ModelViewerProps {
  url: string | null;
  /** "stl" (plain geometry) or "glb" (a painted preview with vertex colours). */
  format?: "stl" | "glb";
  bodyId: string;
  selected: boolean;
  onSelect: (selected: boolean) => void;
  onMeasure?: (size: Size | null) => void;
  height?: number;
  /** What a one-pointer drag does. */
  mode?: DrawMode;
  /** The colour a paint stroke is drawn in. */
  paintColour?: string;
  brushMm?: number;
  /** A finished outline or stroke, in model mm; null when the drag was only a tap. */
  onRegion?: (region: RegionSelection | null) => void;
}

interface Scene {
  gl: ExpoWebGLRenderingContext;
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  mesh: THREE.Mesh | null;
  material: THREE.MeshStandardMaterial;
  /** The path being drawn, shown on top of the model. */
  trail: THREE.Line;
  /** Model mm → the centred scene the mesh is drawn in. */
  offset: THREE.Vector3;
}

/** Reads a GLB (single-file glTF) into one geometry in millimetres. */
function parseGlb(buffer: ArrayBuffer): Promise<THREE.BufferGeometry> {
  return new Promise((resolve, reject) => {
    new GLTFLoader().parse(
      buffer,
      "",
      (gltf) => {
        gltf.scene.updateMatrixWorld(true);
        let first: THREE.Mesh | null = null;
        gltf.scene.traverse((child) => {
          if (!first && (child as THREE.Mesh).isMesh) first = child as THREE.Mesh;
        });
        if (!first) {
          reject(new Error("the file has no mesh"));
          return;
        }
        const mesh = first as THREE.Mesh;
        const geometry = mesh.geometry.clone();
        geometry.applyMatrix4(mesh.matrixWorld);
        geometry.scale(1000, 1000, 1000); // glTF is metres; the platform is millimetres
        resolve(geometry);
      },
      reject,
    );
  });
}

/** three needs a canvas-shaped object; expo-gl gives us the context itself. */
function makeRenderer(gl: ExpoWebGLRenderingContext): THREE.WebGLRenderer {
  const canvas = {
    width: gl.drawingBufferWidth,
    height: gl.drawingBufferHeight,
    clientWidth: gl.drawingBufferWidth,
    clientHeight: gl.drawingBufferHeight,
    style: {},
    addEventListener: () => {},
    removeEventListener: () => {},
    getContext: () => gl,
  } as unknown as HTMLCanvasElement;
  const renderer = new THREE.WebGLRenderer({ canvas, context: gl as never, antialias: true });
  renderer.setSize(gl.drawingBufferWidth, gl.drawingBufferHeight, false);
  renderer.setClearColor(colors.viewport);
  return renderer;
}

export function ModelViewer({
  url,
  format = "stl",
  bodyId,
  selected,
  onSelect,
  onMeasure,
  height = 320,
  mode = "orbit",
  paintColour = "#ff5533",
  brushMm = 5,
  onRegion,
}: ModelViewerProps) {
  const sceneRef = useRef<Scene | null>(null);
  const orbit = useRef({ theta: Math.PI / 4, phi: Math.PI / 3, radius: 200, panX: 0, panY: 0 });
  const start = useRef({ ...orbit.current });
  const [size, setSize] = useState<Size | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pointer, setPointer] = useState<"touch" | "stylus">("touch");
  const [pressure, setPressure] = useState<number | null>(null);
  const [coloured, setColoured] = useState(false);
  // The drag in progress: the surface it started on and the path in model mm.
  const surface = useRef<Surface | null>(null);
  const path = useRef<Point2[]>([]);
  const trailPoints = useRef<THREE.Vector3[]>([]);
  const layout = useRef({ width: 1, height: 1 });
  const drawing = mode !== "orbit";

  const place = useCallback(() => {
    const current = sceneRef.current;
    if (!current) return;
    const { theta, phi, radius, panX, panY } = orbit.current;
    const sinPhi = Math.sin(phi);
    current.camera.position.set(
      panX + radius * sinPhi * Math.cos(theta),
      panY + radius * sinPhi * Math.sin(theta),
      radius * Math.cos(phi),
    );
    current.camera.up.set(0, 0, 1);
    current.camera.lookAt(panX, panY, 0);
  }, []);

  // --- load the model ------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    setError(null);
    if (!url) {
      setSize(null);
      onMeasure?.(null);
      return;
    }
    void (async () => {
      try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`model download failed (${response.status})`);
        const buffer = await response.arrayBuffer();
        const geometry =
          format === "glb" ? await parseGlb(buffer) : new STLLoader().parse(buffer);
        if (cancelled) return;
        const hasColours = Boolean(geometry.attributes.color);
        setColoured(hasColours);
        if (!geometry.attributes.normal) geometry.computeVertexNormals();
        geometry.computeBoundingBox();
        const box = geometry.boundingBox ?? new THREE.Box3();
        const centre = box.getCenter(new THREE.Vector3());
        geometry.translate(-centre.x, -centre.y, -centre.z);
        const extent = box.getSize(new THREE.Vector3());
        setSize({ x: extent.x, y: extent.y, z: extent.z });
        onMeasure?.({ x: extent.x, y: extent.y, z: extent.z });

        const current = sceneRef.current;
        orbit.current.radius = Math.max(extent.length(), 1) * 1.6;
        orbit.current.panX = 0;
        orbit.current.panY = 0;
        if (current) {
          if (current.mesh) {
            current.scene.remove(current.mesh);
            current.mesh.geometry.dispose();
          }
          current.offset.copy(centre);
          current.material.vertexColors = hasColours;
          current.material.needsUpdate = true;
          current.mesh = new THREE.Mesh(geometry, current.material);
          current.scene.add(current.mesh);
          current.camera.far = orbit.current.radius * 40;
          current.camera.updateProjectionMatrix();
          place();
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "failed to load the model");
      }
    })();
    return () => {
      cancelled = true;
    };
    // onMeasure is a callback prop; its identity must not re-download the model.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, format, place]);

  useEffect(() => {
    const current = sceneRef.current;
    // A painted model carries its own colours; tinting it would hide the user's work.
    if (current) {
      current.material.color.set(coloured ? "#ffffff" : selected ? colors.accent : "#c9ced8");
    }
  }, [selected, coloured]);

  // --- drawing on the model (T-105 / T-109) --------------------------------------------
  /** Ray-cast a point in the view's own pixels onto the model; model mm or null. */
  const hitAt = useCallback((x: number, y: number) => {
    const current = sceneRef.current;
    if (!current?.mesh) return null;
    const ndc = new THREE.Vector2(
      (x / layout.current.width) * 2 - 1,
      -(y / layout.current.height) * 2 + 1,
    );
    const caster = new THREE.Raycaster();
    caster.setFromCamera(ndc, current.camera);
    const [hit] = caster.intersectObject(current.mesh, false);
    if (!hit || !hit.face) return null;
    const normal = hit.face.normal.clone().transformDirection(current.mesh.matrixWorld);
    return { scene: hit.point.clone(), point: hit.point.clone().add(current.offset), normal };
  }, []);

  const showTrail = useCallback(() => {
    const current = sceneRef.current;
    if (!current) return;
    const points = trailPoints.current;
    current.trail.geometry.dispose();
    current.trail.geometry = new THREE.BufferGeometry().setFromPoints(
      points.length ? points : [new THREE.Vector3()],
    );
    current.trail.visible = points.length > 1;
    (current.trail.material as THREE.LineBasicMaterial).color.set(
      mode === "paint" ? paintColour : colors.accent,
    );
  }, [mode, paintColour]);

  const drawStart = useCallback(
    (x: number, y: number) => {
      surface.current = null;
      path.current = [];
      trailPoints.current = [];
      const hit = hitAt(x, y);
      if (hit) {
        const facing = dominantAxis(hit.normal);
        surface.current = { ...facing, offset_mm: hit.point[facing.axis] };
        const plane = planeAxes(facing.axis);
        path.current = [[hit.point[plane[0]], hit.point[plane[1]]]];
        trailPoints.current = [hit.scene];
      }
      showTrail();
    },
    [hitAt, showTrail],
  );

  const drawMove = useCallback(
    (x: number, y: number) => {
      const hit = hitAt(x, y);
      if (!hit) return;
      if (!surface.current) {
        const facing = dominantAxis(hit.normal);
        surface.current = { ...facing, offset_mm: hit.point[facing.axis] };
      }
      const plane = planeAxes(surface.current.axis);
      path.current.push([hit.point[plane[0]], hit.point[plane[1]]]);
      trailPoints.current.push(hit.scene);
      showTrail();
    },
    [hitAt, showTrail],
  );

  const drawEnd = useCallback(() => {
    const face = surface.current;
    const selection =
      face && size
        ? pathToRegion(path.current, {
            surface: face,
            modelSize: size,
            bodyId,
            brushMm: mode === "paint" ? brushMm : undefined,
          })
        : null;
    if (!selection) {
      trailPoints.current = [];
      showTrail();
    }
    onRegion?.(selection);
  }, [size, bodyId, mode, brushMm, onRegion, showTrail]);

  // A new drag mode starts with a clean slate.
  useEffect(() => {
    trailPoints.current = [];
    showTrail();
  }, [mode, showTrail]);

  // --- gestures (T-054) ----------------------------------------------------------------
  const pan = Gesture.Pan()
    .runOnJS(true)
    .onStart((event) => {
      start.current = { ...orbit.current };
      if (drawing && event.numberOfPointers === 1) drawStart(event.x, event.y);
    })
    .onUpdate((event) => {
      const stylus = Boolean(event.stylusData);
      if (stylus) {
        setPointer("stylus");
        setPressure(event.stylusData?.pressure ?? null);
      }
      if (drawing && event.numberOfPointers === 1) {
        drawMove(event.x, event.y);
        return;
      }
      if (event.numberOfPointers > 1) {
        // Two fingers slide the model; one orbits it.
        orbit.current.panX = start.current.panX - event.translationX * orbit.current.radius * 0.002;
        orbit.current.panY = start.current.panY + event.translationY * orbit.current.radius * 0.002;
      } else {
        orbit.current.theta = start.current.theta - event.translationX * 0.01;
        orbit.current.phi = Math.min(
          Math.PI - 0.05,
          Math.max(0.05, start.current.phi - event.translationY * 0.01),
        );
      }
      place();
    })
    .onEnd(() => {
      setPressure(null);
      if (drawing) drawEnd();
    });

  const pinch = Gesture.Pinch()
    .onStart(() => {
      start.current = { ...orbit.current };
    })
    .onUpdate((event) => {
      orbit.current.radius = Math.min(
        Math.max(start.current.radius / Math.max(event.scale, 0.05), 1),
        100_000,
      );
      place();
    });

  // Tap events carry no stylus payload; the pan gesture above is what identifies a pencil.
  const tap = Gesture.Tap()
    .runOnJS(true)
    .onEnd((_event, success) => {
      if (success && !drawing) onSelect(!selected);
    });

  const gesture = Gesture.Simultaneous(Gesture.Race(tap, pan), pinch);

  const onContextCreate = useCallback(
    (gl: ExpoWebGLRenderingContext) => {
      try {
        const renderer = makeRenderer(gl);
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(colors.viewport);
        const camera = new THREE.PerspectiveCamera(
          50,
          gl.drawingBufferWidth / gl.drawingBufferHeight,
          0.1,
          10_000,
        );
        scene.add(new THREE.AmbientLight(0xffffff, 0.7));
        const key = new THREE.DirectionalLight(0xffffff, 1.1);
        key.position.set(1, 2, 3);
        scene.add(key);
        const fill = new THREE.DirectionalLight(0xffffff, 0.35);
        fill.position.set(-2, -1, 1);
        scene.add(fill);
        const material = new THREE.MeshStandardMaterial({
          color: selected ? colors.accent : "#c9ced8",
          metalness: 0.05,
          roughness: 0.6,
        });
        const trail = new THREE.Line(
          new THREE.BufferGeometry().setFromPoints([new THREE.Vector3()]),
          new THREE.LineBasicMaterial({ color: colors.accent, depthTest: false }),
        );
        trail.renderOrder = 10;
        trail.visible = false;
        scene.add(trail);
        sceneRef.current = {
          gl,
          renderer,
          scene,
          camera,
          mesh: null,
          material,
          trail,
          offset: new THREE.Vector3(),
        };
        place();

        const draw = () => {
          const current = sceneRef.current;
          if (!current) return;
          requestAnimationFrame(draw);
          current.renderer.render(current.scene, current.camera);
          current.gl.endFrameEXP();
        };
        draw();
      } catch (err) {
        setError(err instanceof Error ? err.message : "3D is unavailable on this device");
      }
    },
    [place, selected],
  );

  return (
    <View
      style={{ height, borderRadius: 10, overflow: "hidden", backgroundColor: colors.viewport }}
      onLayout={(event) => {
        const { width, height: h } = event.nativeEvent.layout;
        layout.current = { width: Math.max(width, 1), height: Math.max(h, 1) };
      }}
    >
      <GestureDetector gesture={gesture}>
        <GLView style={{ flex: 1 }} onContextCreate={onContextCreate} />
      </GestureDetector>
      <View
        style={{
          position: "absolute",
          left: 8,
          bottom: 8,
          flexDirection: "row",
          flexWrap: "wrap",
          gap: 6,
        }}
      >
        {size && (
          <View style={styles.chip}>
            <Text style={styles.chipText}>
              {size.x.toFixed(1)} × {size.y.toFixed(1)} × {size.z.toFixed(1)} mm
            </Text>
          </View>
        )}
        <View style={[styles.chip, selected && { borderColor: colors.accent }]}>
          <Text style={[styles.chipText, selected && { color: colors.accent }]}>{bodyId}</Text>
        </View>
        {!url && (
          <View style={styles.chip}>
            <Text style={styles.chipText}>no model yet</Text>
          </View>
        )}
        {error && (
          <View style={styles.chip}>
            <Text style={[styles.chipText, { color: colors.red }]}>{error}</Text>
          </View>
        )}
        <View style={styles.chip}>
          <Text style={styles.chipText}>
            {mode === "paint"
              ? `sweep to paint · ${brushMm} mm brush`
              : mode === "outline"
                ? "draw around the area to change"
                : pointer === "stylus"
                  ? `pencil${pressure != null ? ` · ${Math.round(pressure * 100)}%` : ""}`
                  : "1 finger: orbit · 2: pan · pinch: zoom · tap: select"}
          </Text>
        </View>
      </View>
    </View>
  );
}
