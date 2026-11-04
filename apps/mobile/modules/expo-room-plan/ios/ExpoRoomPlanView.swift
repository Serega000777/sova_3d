import ARKit
import ExpoModulesCore
import RoomPlan
import simd
import UIKit

@available(iOS 17.0, *)
@MainActor
private final class RoomPlanStructureSession {
  let arSession = ARSession()
  var rooms: [CapturedRoom] = []

  init() {
    // RoomCaptureView's shared-session initializer requires an already-running world
    // tracking session. Keeping this same instance alive is what gives every room one
    // compatible coordinate frame for StructureBuilder.
    arSession.run(ARWorldTrackingConfiguration())
  }
}

@MainActor
private enum RoomPlanStructureRegistry {
  @available(iOS 17.0, *)
  static var sessions: [String: RoomPlanStructureSession] = [:]

  @available(iOS 17.0, *)
  static func session(for id: String) -> RoomPlanStructureSession {
    if let existing = sessions[id] { return existing }
    sessions.values.forEach { $0.arSession.pause() }
    let created = RoomPlanStructureSession()
    sessions = [id: created]
    return created
  }
}

/// Hosts Apple's own `RoomCaptureView` — this class adds no AR rendering of its own, only
/// the plumbing from its declarative `capturing` prop to RoomPlan's session lifecycle, and
/// from its delegate callbacks to Expo's event dispatchers.
///
/// The class itself has no `@available` gate (an Expo Modules `View(...)` registration
/// must be reachable from code that runs on every supported OS version), so every actual
/// RoomPlan type is confined to `@available(iOS 16.0, *)`-guarded methods and extensions
/// below; `captureView` is stored as a plain `UIView` and downcast where needed.
public class ExpoRoomPlanView: ExpoView {
  private var captureView: UIView?
  private var capturing = false
  private var structureSessionId: String?

  let onRoomUpdate = EventDispatcher()
  let onInstruction = EventDispatcher()
  let onCaptureFinish = EventDispatcher()
  let onCaptureError = EventDispatcher()

  public required init(appContext: AppContext? = nil) {
    super.init(appContext: appContext)
  }

  func setStructureSessionId(_ sessionId: String) {
    guard !sessionId.isEmpty, sessionId != structureSessionId else { return }
    structureSessionId = sessionId
    setUpIfAvailable(sessionId: sessionId)
    if capturing { applyCapturing(true) }
  }

  private func setUpIfAvailable(sessionId: String) {
    guard #available(iOS 16.0, *) else { return }
    captureView?.removeFromSuperview()
    let view: RoomCaptureView
    if #available(iOS 17.0, *) {
      view = RoomCaptureView(
        frame: .zero,
        arSession: RoomPlanStructureRegistry.session(for: sessionId).arSession
      )
    } else {
      view = RoomCaptureView(frame: .zero)
    }
    view.delegate = self
    view.captureSession.delegate = self
    view.translatesAutoresizingMaskIntoConstraints = false
    addSubview(view)
    NSLayoutConstraint.activate([
      view.topAnchor.constraint(equalTo: topAnchor),
      view.bottomAnchor.constraint(equalTo: bottomAnchor),
      view.leadingAnchor.constraint(equalTo: leadingAnchor),
      view.trailingAnchor.constraint(equalTo: trailingAnchor),
    ])
    captureView = view
  }

  /// Driven by the `capturing` prop (`ExpoRoomPlanModule`), not an imperative call: the
  /// session starts on the false→true edge and stops (handing off to RoomPlan's own
  /// post-processing, which ends in `captureView(didPresent:error:)` below) on true→false.
  func setCapturing(_ value: Bool) {
    guard value != capturing else { return }
    capturing = value

    // Expo may apply props in either order. Wait for the stable structure session id so
    // the first room cannot accidentally begin in a throwaway ARSession.
    guard structureSessionId != nil else { return }
    applyCapturing(value)
  }

  private func applyCapturing(_ value: Bool) {
    guard #available(iOS 16.0, *), let view = captureView as? RoomCaptureView else {
      if value {
        onCaptureError(["message": "RoomPlan needs iOS 16 or later."])
        capturing = false
      }
      return
    }

    if value {
      guard RoomCaptureSession.isSupported else {
        onCaptureError(["message": "This device has no LiDAR sensor RoomPlan can use."])
        capturing = false
        return
      }
      view.captureSession.run(configuration: RoomCaptureSession.Configuration())
    } else {
      if #available(iOS 17.0, *) {
        // Apple requires the same live ARSession for rooms that StructureBuilder merges.
        view.captureSession.stop(pauseARSession: false)
      } else {
        view.captureSession.stop()
      }
    }
  }
}

// MARK: - Live feedback while scanning

@available(iOS 16.0, *)
extension ExpoRoomPlanView: RoomCaptureSessionDelegate {
  public func captureSession(_ session: RoomCaptureSession, didUpdate room: CapturedRoom) {
    onRoomUpdate([
      "walls": room.walls.count,
      "openings": room.doors.count + room.windows.count + room.openings.count,
      "doors": room.doors.count,
      "windows": room.windows.count,
      "objects": room.objects.count,
    ])
  }

  public func captureSession(
    _ session: RoomCaptureSession,
    didProvide instruction: RoomCaptureSession.Instruction
  ) {
    onInstruction(["instruction": String(describing: instruction)])
  }
}

// MARK: - Post-processing once the session stops (RoomCaptureView does the building)

@available(iOS 16.0, *)
extension ExpoRoomPlanView: RoomCaptureViewDelegate {
  public func captureView(shouldPresent roomDataForProcessing: CapturedRoomData, error: Error?) -> Bool {
    // Always let RoomPlan finish building the room; a mid-session error still hands back
    // whatever it could reconstruct, which `didPresent` below reports honestly either way.
    return true
  }

  public func captureView(didPresent processedResult: CapturedRoom, error: Error?) {
    // A mid-session tracking error does not discard what RoomPlan already reconstructed
    // (see `shouldPresent` above) — salvage it when there is enough geometry to be useful,
    // and only give up when the result genuinely has too little to work with. Matches the
    // server's own `RoomPlanCapture.walls` minimum (app/engineering/room_plan.py).
    let minUsableWalls = 3
    let destination = FileManager.default.temporaryDirectory
      .appendingPathComponent("room-\(UUID().uuidString).usdz")
    do {
      // .mesh: the actual scanned surface, not RoomPlan's idealized parametric walls —
      // this platform's pipeline (worker.reconstruction's fusion path) wants real geometry.
      try processedResult.export(to: destination, exportOptions: .mesh)
      let walls = processedResult.walls.compactMap { roomPlanWall($0) }
      let openings = processedResult.doors.compactMap { roomPlanOpening($0, kind: "door") }
        + processedResult.openings.compactMap { roomPlanOpening($0, kind: "opening") }
        + processedResult.windows.compactMap { roomPlanOpening($0, kind: "window") }
      if let error, walls.count < minUsableWalls {
        onCaptureError([
          "message": "Трекинг потерян, а стен распознано слишком мало (\(walls.count)): "
            + "\(error.localizedDescription). Переснимите комнату при более ярком свете и медленнее двигайте телефон.",
        ])
        return
      }
      var payload: [String: Any] = [
        "usdzPath": destination.path,
        "walls": processedResult.walls.count,
        "openings": processedResult.doors.count + processedResult.windows.count
          + processedResult.openings.count,
        "doors": processedResult.doors.count,
        "windows": processedResult.windows.count,
        "objects": processedResult.objects.count,
        "roomPlan": roomPlanPayload(processedResult, walls: walls, openings: openings),
      ]
      if let error {
        payload["trackingWarning"] =
          "Трекинг на секунду терялся во время съёмки — часть геометрии может быть неполной (\(error.localizedDescription))."
      }
      if #available(iOS 17.0, *), let sessionId = structureSessionId {
        let state = RoomPlanStructureRegistry.session(for: sessionId)
        state.rooms.append(processedResult)
        guard state.rooms.count >= 2 else {
          onCaptureFinish(payload)
          return
        }
        let rooms = state.rooms
        Task { @MainActor [weak self] in
          guard let self else { return }
          do {
            let structure = try await StructureBuilder().capturedStructure(from: rooms)
            let structureDestination = FileManager.default.temporaryDirectory
              .appendingPathComponent("structure-\(UUID().uuidString).usdz")
            try structure.export(to: structureDestination)
            payload["structure"] = [
              "schema_version": 1,
              "structure_id": structure.identifier.uuidString,
              "coordinate_space": "shared_arkit_world",
              "rooms": structure.rooms.map { self.roomPlanPayload($0) },
              "usdzPath": structureDestination.path,
            ]
          } catch {
            payload["structureError"] =
              "RoomPlan не смог объединить комнаты в одном координатном пространстве: \(error.localizedDescription)"
          }
          self.onCaptureFinish(payload)
        }
      } else {
        onCaptureFinish(payload)
      }
    } catch {
      onCaptureError(["message": "USDZ export failed: \(error.localizedDescription)"])
    }
  }

  private func roomPlanPayload(
    _ room: CapturedRoom,
    walls: [[String: Any]]? = nil,
    openings: [[String: Any]]? = nil
  ) -> [String: Any] {
    let roomWalls = walls ?? room.walls.compactMap { roomPlanWall($0) }
    let roomOpenings = openings
      ?? (room.doors.compactMap { roomPlanOpening($0, kind: "door") }
        + room.openings.compactMap { roomPlanOpening($0, kind: "opening") }
        + room.windows.compactMap { roomPlanOpening($0, kind: "window") })
    let floorElevations = room.walls
      .map { Double($0.transform.columns.3.y - $0.dimensions.y / 2) }
      .sorted()
    var payload: [String: Any] = [
      "schema_version": 2,
      "room_id": room.identifier.uuidString,
      "walls": roomWalls,
      "openings": roomOpenings,
    ]
    if !floorElevations.isEmpty {
      payload["floor_elevation_m"] = floorElevations[floorElevations.count / 2]
    }
    return payload
  }

  /// RoomPlan defines a wall as a transformed 2D surface. Its local X axis and X dimension
  /// give the metric centre-line endpoints; world X/Z become the shared plan's X/Y plane.
  private func roomPlanWall(_ surface: CapturedRoom.Surface) -> [String: Any]? {
    let transform = surface.transform
    let center = SIMD2<Float>(transform.columns.3.x, transform.columns.3.z)
    var axis = SIMD2<Float>(transform.columns.0.x, transform.columns.0.z)
    let axisLength = simd_length(axis)
    guard axisLength > 0.0001, surface.dimensions.x > 0 else { return nil }
    axis /= axisLength
    let half = axis * (surface.dimensions.x / 2)
    let a = center - half
    let b = center + half
    return [
      "identifier": surface.identifier.uuidString,
      "a_m": [Double(a.x), Double(a.y)],
      "b_m": [Double(b.x), Double(b.y)],
      "height_m": Double(surface.dimensions.y),
      "transform_m": matrixValues(transform),
      "dimensions_m": dimensionsValues(surface.dimensions),
    ]
  }

  private func roomPlanOpening(
    _ surface: CapturedRoom.Surface,
    kind: String
  ) -> [String: Any]? {
    let transform = surface.transform
    guard surface.dimensions.x > 0 else { return nil }
    // `parentIdentifier` was added in iOS 17. Keep RoomPlan capture available on iOS 16;
    // the API already has a conservative geometric fallback when the parent is absent.
    let parent: Any
    if #available(iOS 17.0, *), let parentIdentifier = surface.parentIdentifier {
      parent = parentIdentifier.uuidString
    } else {
      parent = NSNull()
    }
    return [
      "identifier": surface.identifier.uuidString,
      "parent_wall_id": parent,
      "center_m": [Double(transform.columns.3.x), Double(transform.columns.3.z)],
      "width_m": Double(surface.dimensions.x),
      "kind": kind,
      "transform_m": matrixValues(transform),
      "dimensions_m": dimensionsValues(surface.dimensions),
    ]
  }

  private func matrixValues(_ matrix: simd_float4x4) -> [Double] {
    [matrix.columns.0, matrix.columns.1, matrix.columns.2, matrix.columns.3]
      .flatMap { column in
        [Double(column.x), Double(column.y), Double(column.z), Double(column.w)]
      }
  }

  private func dimensionsValues(_ dimensions: SIMD3<Float>) -> [Double] {
    [Double(dimensions.x), Double(dimensions.y), Double(dimensions.z)]
  }
}
