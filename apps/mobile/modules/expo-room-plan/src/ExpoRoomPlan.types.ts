/** T-196: lightweight live progress while RoomPlan is still scanning. */
export interface RoomProgress {
  walls: number;
  openings: number;
  objects: number;
}

export interface RoomUpdateEvent extends RoomProgress {}

export interface InstructionEvent {
  /** A RoomPlan `RoomCaptureSession.Instruction` case name (e.g. "moveCloseToWall",
   * "turnOnLight", "normal") — mapped to user-facing copy on the JS side, not here, so
   * wording changes do not need a native rebuild. */
  instruction: string;
}

/** Metric X/Z projection of one wall surface, prepared natively from RoomPlan's transform. */
export interface RoomPlanWallSurface {
  identifier: string;
  a_m: [number, number];
  b_m: [number, number];
  height_m: number;
}

/** Door/window centre in the same metric X/Z coordinate system as the walls. */
export interface RoomPlanOpeningSurface {
  identifier: string;
  parent_wall_id: string | null;
  center_m: [number, number];
  width_m: number;
  kind: "door" | "window" | "opening";
}

export interface RoomPlanCapture {
  room_id: string;
  walls: RoomPlanWallSurface[];
  openings: RoomPlanOpeningSurface[];
}

export interface CaptureFinishEvent extends RoomProgress {
  /** Absolute path to a USDZ file in the app's temporary directory (T-196 acceptance:
   * "exportable geometry"). The caller must move/upload it — it will not survive an
   * OS cleanup of the temp directory. */
  usdzPath: string;
  /** Server-ready metric wall/opening primitives. The server validates and snaps these
   * before persisting a 2D floor plan; JS never parses the USDZ mesh. */
  /** Missing only when current JS is running inside an older development build; rebuilding
   * the native app upgrades the bridge. */
  roomPlan?: RoomPlanCapture;
}

export interface CaptureErrorEvent {
  message: string;
}

export interface RoomCaptureViewProps {
  /** Declarative, not imperative: RoomPlan's session starts when this becomes true and
   * stops (triggering its own post-processing, then `onCaptureFinish`) when it becomes
   * false. There is no `startCapture()`/`stopCapture()` ref method to call instead. */
  capturing: boolean;
  onRoomUpdate?: (event: { nativeEvent: RoomUpdateEvent }) => void;
  onInstruction?: (event: { nativeEvent: InstructionEvent }) => void;
  onCaptureFinish?: (event: { nativeEvent: CaptureFinishEvent }) => void;
  onCaptureError?: (event: { nativeEvent: CaptureErrorEvent }) => void;
  style?: object;
}
