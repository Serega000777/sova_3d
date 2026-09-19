"use client";

/**
 * Live view of a scan in progress (F-082): every fragment the scanner delivered so far —
 * meshes as surfaces, point clouds as points — placed where the platform will fuse them.
 * Fragments arrive while the user watches; the camera re-frames as the model grows.
 */
import { Grid, OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";
import { PLYLoader } from "three/examples/jsm/loaders/PLYLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

export interface FragmentSource {
  id: string;
  url: string;
  kind: "mesh" | "pointcloud" | string;
  format: string; // stl | ply | obj
  /** {matrix: 4x4} or {azimuth_deg, turntable_centre_mm} — the same convention as the worker. */
  pose: Record<string, unknown>;
}

interface Loaded {
  id: string;
  geometry: THREE.BufferGeometry;
  points: boolean;
  matrix: THREE.Matrix4;
}

/** The fragment's placement, mirroring worker.reconstruction.pose_matrix. */
function poseMatrix(pose: Record<string, unknown>): THREE.Matrix4 {
  const matrix = new THREE.Matrix4();
  const raw = pose.matrix;
  if (Array.isArray(raw) && raw.length === 4) {
    const rows = raw as number[][];
    matrix.set(
      rows[0][0], rows[0][1], rows[0][2], rows[0][3],
      rows[1][0], rows[1][1], rows[1][2], rows[1][3],
      rows[2][0], rows[2][1], rows[2][2], rows[2][3],
      rows[3][0], rows[3][1], rows[3][2], rows[3][3],
    );
    return matrix;
  }
  const azimuth = pose.azimuth_deg;
  if (typeof azimuth === "number") {
    const centre = Array.isArray(pose.turntable_centre_mm)
      ? new THREE.Vector3(...(pose.turntable_centre_mm as [number, number, number]))
      : new THREE.Vector3();
    const rotation = new THREE.Matrix4().makeRotationZ(-THREE.MathUtils.degToRad(azimuth));
    matrix
      .makeTranslation(centre.x, centre.y, centre.z)
      .multiply(rotation)
      .multiply(new THREE.Matrix4().makeTranslation(-centre.x, -centre.y, -centre.z));
  }
  const translation = pose.translation_mm;
  if (Array.isArray(translation) && translation.length === 3) {
    const [x, y, z] = translation as [number, number, number];
    matrix.premultiply(new THREE.Matrix4().makeTranslation(x, y, z));
  }
  return matrix;
}

function Frame({ bounds }: { bounds: THREE.Box3 | null }) {
  const { camera, controls } = useThree();
  useEffect(() => {
    if (!bounds || bounds.isEmpty()) return;
    const centre = bounds.getCenter(new THREE.Vector3());
    const radius = Math.max(bounds.getBoundingSphere(new THREE.Sphere()).radius, 10);
    camera.position.set(centre.x + radius * 1.6, centre.y - radius * 1.6, centre.z + radius * 1.2);
    camera.lookAt(centre);
    const orbit = controls as { target?: THREE.Vector3; update?: () => void } | null;
    if (orbit?.target) {
      orbit.target.copy(centre);
      orbit.update?.();
    }
  }, [bounds, camera, controls]);
  return null;
}

const PALETTE = ["#5b9cff", "#35c48d", "#ffb020", "#b06bff", "#ff5533", "#4dd0e1", "#f2f2f2"];

export function FragmentsViewer({
  fragments,
  height = 420,
}: {
  fragments: FragmentSource[];
  height?: number;
}) {
  const [loaded, setLoaded] = useState<Loaded[]>([]);

  useEffect(() => {
    let cancelled = false;
    const missing = fragments.filter((f) => !loaded.some((l) => l.id === f.id));
    // STL fragments are meshes; a PLY may be either and is told apart once decoded
    for (const fragment of missing) {
      const loader = fragment.format === "ply" ? new PLYLoader() : new STLLoader();
      loader.load(
        fragment.url,
        (geometry: THREE.BufferGeometry) => {
          if (cancelled) return;
          // a PLY with no faces is a point cloud whatever the frame says
          const points =
            fragment.kind === "pointcloud" ||
            (geometry.index === null &&
              fragment.format === "ply" &&
              !geometry.getAttribute("normal"));
          geometry.computeBoundingBox();
          if (!points) geometry.computeVertexNormals();
          setLoaded((current) =>
            current.some((l) => l.id === fragment.id)
              ? current
              : [
                  ...current,
                  { id: fragment.id, geometry, points, matrix: poseMatrix(fragment.pose) },
                ],
          );
        },
        undefined,
        () => undefined, // a fragment that fails to load is simply not shown
      );
    }
    return () => {
      cancelled = true;
    };
    // loaded is read to skip what is already there; re-running on it would loop
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fragments]);

  const bounds = useMemo(() => {
    const box = new THREE.Box3();
    for (const item of loaded) {
      // the vertices themselves, placed: a rotated bounding box would overstate the size
      const placed = new THREE.Mesh(item.geometry);
      placed.matrixAutoUpdate = false;
      placed.matrix.copy(item.matrix);
      placed.matrixWorld.copy(item.matrix);
      box.expandByObject(placed, true);
    }
    return box.isEmpty() ? null : box;
  }, [loaded]);

  return (
    <div className="viewport" style={{ height }}>
      <Canvas camera={{ position: [200, -200, 150], near: 0.5, far: 5000, up: [0, 0, 1] }}>
        <color attach="background" args={["#0b0d12"]} />
        <ambientLight intensity={0.6} />
        <directionalLight position={[200, 300, 400]} intensity={1.1} />
        <directionalLight position={[-200, -100, 100]} intensity={0.4} />
        {loaded.map((item, index) =>
          item.points ? (
            <points
              key={item.id}
              geometry={item.geometry}
              matrixAutoUpdate={false}
              matrix={item.matrix}
            >
              <pointsMaterial size={1.2} color={PALETTE[index % PALETTE.length]} sizeAttenuation />
            </points>
          ) : (
            <mesh
              key={item.id}
              geometry={item.geometry}
              matrixAutoUpdate={false}
              matrix={item.matrix}
            >
              <meshStandardMaterial
                color={PALETTE[index % PALETTE.length]}
                roughness={0.6}
                metalness={0.05}
                side={THREE.DoubleSide}
              />
            </mesh>
          ),
        )}
        <Grid
          args={[2000, 2000]}
          cellSize={10}
          sectionSize={50}
          rotation={[Math.PI / 2, 0, 0]}
          position={[0, 0, bounds ? bounds.min.z : 0]}
          cellColor="#2a2f3a"
          sectionColor="#3a4150"
          fadeDistance={1500}
          infiniteGrid
        />
        <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
        <Frame bounds={bounds} />
      </Canvas>
      <div className="hud">
        <span className="chip">{loaded.length} fragment(s)</span>
        {bounds && (
          <span className="chip mono">
            {bounds.getSize(new THREE.Vector3()).toArray().map((v) => v.toFixed(0)).join(" × ")} mm
          </span>
        )}
      </div>
    </div>
  );
}
