import ExpoModulesCore
import RoomPlan

/// T-196: the JS-facing surface is two things only — "can this device do it at all" and
/// the `ExpoRoomPlanView` that hosts Apple's own `RoomCaptureView`. Everything else
/// (session lifecycle, post-processing, USDZ export) lives on the view, driven by props
/// and reported back through events, so there is nothing here to get out of sync with a
/// view instance that may not exist yet.
public class ExpoRoomPlanModule: Module {
  public func definition() -> ModuleDefinition {
    Name("ExpoRoomPlan")

    Function("isSupported") { () -> Bool in
      if #available(iOS 16.0, *) {
        return RoomCaptureSession.isSupported
      }
      return false
    }

    View(ExpoRoomPlanView.self) {
      Events("onRoomUpdate", "onInstruction", "onCaptureFinish", "onCaptureError")

      Prop("capturing") { (view: ExpoRoomPlanView, capturing: Bool) in
        view.setCapturing(capturing)
      }
    }
  }
}
