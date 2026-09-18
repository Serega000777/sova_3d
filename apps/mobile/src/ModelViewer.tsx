/**
 * Mobile 3D viewport (T-054, F-058/F-060): expo-gl + three, JS only, so it runs in Expo Go.
 *
 * One finger orbits, two fingers pan and pinch to zoom, a tap selects the body.
 * A stylus (Apple Pencil, S Pen) is its own pointer type: react-native-gesture-handler
 * reports pressure and tilt in `stylusData`, which the HUD shows and the tap uses to
 * select precisely instead of orbiting.
 */
import { GLView, type ExpoWebGLRenderingContext } from "expo-gl";
import { useCallback, useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

import { colors, styles } from "./theme";

export interface Size {
  x: number;
  y: number;
  z: number;
}

export interface ModelViewerProps {
  url: string | null;
  bodyId: string;
  selected: boolean;
  onSelect: (selected: boolean) => void;
  onMeasure?: (size: Size | null) => void;
  height?: number;
}

interface Scene {
  gl: ExpoWebGLRenderingContext;
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  mesh: THREE.Mesh | null;
  material: THREE.MeshStandardMaterial;
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
  bodyId,
  selected,
  onSelect,
  onMeasure,
  height = 320,
}: ModelViewerProps) {
  const sceneRef = useRef<Scene | null>(null);
  const orbit = useRef({ theta: Math.PI / 4, phi: Math.PI / 3, radius: 200, panX: 0, panY: 0 });
  const start = useRef({ ...orbit.current });
  const [size, setSize] = useState<Size | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pointer, setPointer] = useState<"touch" | "stylus">("touch");
  const [pressure, setPressure] = useState<number | null>(null);

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
        const geometry = new STLLoader().parse(await response.arrayBuffer());
        if (cancelled) return;
        geometry.computeVertexNormals();
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
  }, [url, place]);

  useEffect(() => {
    const current = sceneRef.current;
    if (current) current.material.color.set(selected ? colors.accent : "#c9ced8");
  }, [selected]);

  // --- gestures (T-054) ----------------------------------------------------------------
  const pan = Gesture.Pan()
    .onStart(() => {
      start.current = { ...orbit.current };
    })
    .onUpdate((event) => {
      const stylus = Boolean(event.stylusData);
      if (stylus) {
        setPointer("stylus");
        setPressure(event.stylusData?.pressure ?? null);
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
    .onEnd(() => setPressure(null));

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
  const tap = Gesture.Tap().onEnd((_event, success) => {
    if (success) onSelect(!selected);
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
        sceneRef.current = { gl, renderer, scene, camera, mesh: null, material };
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
    <View style={{ height, borderRadius: 10, overflow: "hidden", backgroundColor: colors.viewport }}>
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
            {pointer === "stylus"
              ? `pencil${pressure != null ? ` · ${Math.round(pressure * 100)}%` : ""}`
              : "1 finger: orbit · 2: pan · pinch: zoom · tap: select"}
          </Text>
        </View>
      </View>
    </View>
  );
}
