/** T-196: what RoomPlan has understood so far, or at the end of a scan — counts only, the
 * geometry itself stays in the exported USDZ so the JS side never parses 3D data by hand. */
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

export interface CaptureFinishEvent extends RoomProgress {
  /** Absolute path to a USDZ file in the app's temporary directory (T-196 acceptance:
   * "exportable geometry"). The caller must move/upload it — it will not survive an
   * OS cleanup of the temp directory. */
  usdzPath: string;
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
