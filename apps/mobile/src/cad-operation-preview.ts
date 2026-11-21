export type CadOperationFeaturePreview = {
  operationId: string;
  kind: "hole" | "thread";
  axis: "x" | "y" | "z";
  sign: "+" | "-";
  positionMm: [number, number];
  diameterMm: number;
};

type CadOperationFactBase = {
  face: `${"x" | "y" | "z"}${"+" | "-"}`;
  positionMm: [number, number];
  direction: "normal_to_face";
  target: string;
};

export type CadOperationFacts = CadOperationFactBase & (
  | { mode: "through"; depthMm: null }
  | { mode: "blind"; depthMm: number }
);

export type CadEdgeDetailFacts = {
  kind: "fillet" | "chamfer";
  target: string;
  amountMm: number;
  selector:
    | { kind: "all_edges" }
    | { kind: "edges_parallel_to"; axis: "x" | "y" | "z"; outer: boolean }
    | { kind: "edges_of_face"; face: "all" | `${"x" | "y" | "z"}${"+" | "-"}` };
};

type OperationEntry = {
  id: string;
  type: string;
  params: Record<string, unknown>;
};

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

export function cadOperationFeaturePreview(
  entry: OperationEntry,
): CadOperationFeaturePreview | null {
  if (entry.type !== "add_hole" && entry.type !== "add_internal_thread") return null;
  const face = record(entry.params.face);
  const position = entry.params.position_mm;
  const axis = face?.axis;
  const sign = face?.sign;
  const diameter = entry.type === "add_internal_thread"
    ? entry.params.major_diameter_mm
    : entry.params.diameter_mm;
  if (
    face?.kind !== "face_by_normal"
    || !["x", "y", "z"].includes(String(axis))
    || (sign !== "+" && sign !== "-")
    || !Array.isArray(position)
    || position.length !== 2
    || position.some((value) => typeof value !== "number" || !Number.isFinite(value))
    || typeof diameter !== "number"
    || !Number.isFinite(diameter)
    || diameter <= 0
  ) return null;
  return {
    operationId: entry.id,
    kind: entry.type === "add_internal_thread" ? "thread" : "hole",
    axis: axis as CadOperationFeaturePreview["axis"],
    sign,
    positionMm: position as [number, number],
    diameterMm: diameter,
  };
}

export function cadOperationFacts(entry: OperationEntry): CadOperationFacts | null {
  const preview = cadOperationFeaturePreview(entry);
  const target = entry.params.target;
  const depth = entry.params.depth_mm;
  if (!preview || typeof target !== "string" || target.length === 0) return null;
  if (depth !== null && depth !== undefined && (
    typeof depth !== "number" || !Number.isFinite(depth) || depth <= 0
  )) return null;
  const mode = depth === null || depth === undefined
    ? { mode: "through" as const, depthMm: null }
    : { mode: "blind" as const, depthMm: depth };
  return {
    ...mode,
    face: `${preview.axis}${preview.sign}`,
    positionMm: preview.positionMm,
    direction: "normal_to_face",
    target,
  };
}

/** Read exact symbolic fillet/chamfer scope without pretending it identifies rendered edge ids. */
export function cadEdgeDetailFacts(entry: OperationEntry): CadEdgeDetailFacts | null {
  if (entry.type !== "fillet" && entry.type !== "chamfer") return null;
  const target = entry.params.target;
  const amount = entry.type === "fillet" ? entry.params.radius_mm : entry.params.distance_mm;
  const edges = record(entry.params.edges);
  if (
    typeof target !== "string"
    || target.length === 0
    || typeof amount !== "number"
    || !Number.isFinite(amount)
    || amount <= 0
    || !edges
  ) return null;

  let selector: CadEdgeDetailFacts["selector"] | null = null;
  if (edges.kind === "all_edges") {
    selector = { kind: "all_edges" };
  } else if (
    edges.kind === "edges_parallel_to"
    && ["x", "y", "z"].includes(String(edges.axis))
    && (edges.outer === undefined || typeof edges.outer === "boolean")
  ) {
    selector = {
      kind: "edges_parallel_to",
      axis: edges.axis as "x" | "y" | "z",
      outer: edges.outer === true,
    };
  } else if (edges.kind === "edges_of_face") {
    const face = record(edges.face);
    if (face?.kind === "all_faces") {
      selector = { kind: "edges_of_face", face: "all" };
    } else if (
      face?.kind === "face_by_normal"
      && ["x", "y", "z"].includes(String(face.axis))
      && (face.sign === "+" || face.sign === "-")
    ) {
      selector = {
        kind: "edges_of_face",
        face: `${face.axis}${face.sign}` as "x+" | "x-" | "y+" | "y-" | "z+" | "z-",
      };
    }
  }
  return selector ? { kind: entry.type, target, amountMm: amount, selector } : null;
}
