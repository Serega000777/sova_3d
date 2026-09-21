# Editor and room scan implementation notes

## Pro editor

The simple editor keeps the model and a short left tool rail in focus. Pro exposes a searchable catalog of **working** operations, grouped into shapes, exact geometry, transforms, inspection and output. Choosing an action opens its actual parameter panel. This follows the discoverable workspace/tool grouping used by [Autodesk Fusion](https://help.autodesk.com/cloudhelp/ENU/Fusion-GetStarted/files/GS-WORKSPACES.htm), the contextual command access in [3ds Max](https://help.autodesk.com/cloudhelp/2027/ENU/3dsMax-Basics/files/3ds_max_interface_overview/GUID-3A803F43-6F87-40FB-97CA-33844078AF9A.html), and the expanded tools in [SketchUp for Web](https://help.sketchup.com/en/sketchup-web/sketchup-web-expanded-toolbar). [Nomad Sculpt](https://nomadsculpt.com/manual/gettingstarted) is the reference for a persistent, scrollable tool rail on smaller screens.

The catalog is an entry point for existing geometry operations. A future developer tier should add capabilities only with real kernel support and tested controls; a long menu of nonworking commands would mislead users.

## iPhone and iPad room scanning

The current mobile route offers object, room and home choices and records RGB photo frames. One home session currently means one room. It does **not** measure depth, detect wall geometry or produce a floor plan.

Native iOS capture (T-196) should use [Apple RoomPlan](https://developer.apple.com/documentation/roomplan) on supported LiDAR devices. RoomPlan provides live feedback and identifies walls, openings, doors and objects. An Expo Go camera screen cannot stand in for this native capture; use an iOS development build and test on a physical device.

Multiroom capture (T-197) should retain the AR session, finish each room separately and combine the resulting rooms with [StructureBuilder](https://developer.apple.com/documentation/roomplan/scanning-the-rooms-of-a-single-structure). The merged structure is the source for a home model; derive and validate the editable 2D plan from its measured walls, openings and room coordinates. Keep RGB reconstruction as an explicit fallback for devices without LiDAR.

[Polycam Space Mode](https://learn.poly.cam/hc/en-us/articles/36655587097620-How-to-Use-Space-Mode-LiDAR-Devices) demonstrates a room-scan flow with a 3D mesh and floor plans. [Planner 5D](https://support.planner5d.com/en/articles/5897614-scan-your-room-ios) demonstrates a guided room capture. These are workflow references, not proof that our current RGB implementation offers equivalent measurements.
