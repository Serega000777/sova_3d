import ExpoModulesCore
import RoomPlan
import UIKit

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

  let onRoomUpdate = EventDispatcher()
  let onInstruction = EventDispatcher()
  let onCaptureFinish = EventDispatcher()
  let onCaptureError = EventDispatcher()

  public required init(appContext: AppContext? = nil) {
    super.init(appContext: appContext)
    setUpIfAvailable()
  }

  private func setUpIfAvailable() {
    guard #available(iOS 16.0, *) else { return }
    let view = RoomCaptureView(frame: .zero)
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
      view.captureSession.stop()
    }
  }
}

// MARK: - Live feedback while scanning

@available(iOS 16.0, *)
extension ExpoRoomPlanView: RoomCaptureSessionDelegate {
  public func captureSession(_ session: RoomCaptureSession, didUpdate room: CapturedRoom) {
    onRoomUpdate([
      "walls": room.walls.count,
      "openings": room.openings.count,
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
    if let error {
      onCaptureError(["message": error.localizedDescription])
      return
    }
    let destination = FileManager.default.temporaryDirectory
      .appendingPathComponent("room-\(UUID().uuidString).usdz")
    do {
      // .mesh: the actual scanned surface, not RoomPlan's idealized parametric walls —
      // this platform's pipeline (worker.reconstruction's fusion path) wants real geometry.
      try processedResult.export(to: destination, exportOptions: .mesh)
      onCaptureFinish([
        "usdzPath": destination.path,
        "walls": processedResult.walls.count,
        "openings": processedResult.openings.count,
        "objects": processedResult.objects.count,
      ])
    } catch {
      onCaptureError(["message": "USDZ export failed: \(error.localizedDescription)"])
    }
  }
}
