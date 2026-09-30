# Mobile app (F-058)

Expo SDK 57 / React Native 0.86, iOS + Android including iPad. The normal product path
runs in Expo Go. The optional Apple RoomPlan LiDAR capture is native iOS code and needs
a development build; its absence never breaks Expo Go or Android.

## Run it in Expo Go

```bash
pnpm --filter @physical-ai/mobile run start:go
```

Scan the QR code with Expo Go (iOS: Camera app; Android: the Expo Go scanner). The
Metro/dev server listens on port 8100.

A phone cannot reach your laptop's `localhost`, so point the app at the machine's LAN
address before starting:

```bash
EXPO_PUBLIC_API_URL=http://192.168.1.50:18000 pnpm --filter @physical-ai/mobile run start:go
```

That address must also be allowed by the API's CORS list (`CORS_ALLOW_ORIGINS` in `.env`)
if you use the web build; native Expo Go requests are not subject to CORS.

Sign in with a phone number or an email (the one-time code is shown on screen while the
server runs with `SIGNIN_DELIVERY=stub`) or with the Yandex ID / VK ID demo buttons.

`pnpm --filter @physical-ai/mobile run web` opens the same app in a browser, which is the
quickest smoke test on a machine with no phone attached.

## What runs where

| Capability | Expo Go | Development build |
| --- | --- | --- |
| Auth, projects, versions, AI commands, exports | yes | yes |
| 3D viewport (expo-gl + three), touch + Apple Pencil | yes | yes |
| Numeric dimension editing | yes | yes |
| Camera capture, guided scan, reconstruction, review | yes | yes |
| Guided exterior building capture (T-232) | yes | yes |
| Apple RoomPlan LiDAR room capture (T-196) | no | yes, on a supported LiDAR device |

The capability probe (`src/capabilities.ts`, T-074) asks RoomPlan itself whether the
device is supported. Expo Go and Android report no LiDAR support and keep the RGB-photo
path available.

## Test RoomPlan on an iPhone or iPad

Requirements: iOS 16+, a LiDAR-equipped device, an Expo account and Apple signing
credentials. Expo Go cannot load `modules/expo-room-plan`.

From `apps/mobile`, sign in and link the app to an EAS project once:

```bash
pnpm dlx eas-cli login
pnpm dlx eas-cli init
```

Build and install the development client:

```bash
pnpm run build:ios:dev
```

Then run Metro on the same network as the device, pointing it at an API address the
device can reach:

```bash
EXPO_PUBLIC_API_URL=http://192.168.1.50:18000 pnpm run start:dev
```

One capture currently produces one measured room and uploads its USDZ mesh. Combining
several rooms into a whole house/building with RoomPlan `StructureBuilder` is T-197 and
must be implemented after this single-room path is validated on hardware.

### The depth-scan boundary

`ScanSession.mode` is `rgb` (photos, works everywhere) or `rgb_depth`. RoomPlan finishes
its native capture as a measured USDZ mesh and uploads that file as a scanner fragment;
the worker's fusion path converts it to the platform's millimetre coordinate system. The
API also accepts lower-level depth frames and poses for future ARKit/ARCore adapters, but
the current iOS RoomPlan path does not stream those frames itself.

## Capture a building exterior

Choose **Building · exterior** on the scan screen. The app treats the front, right,
back and left facades as four required passes and shows their measured frame coverage;
roof photos are optional and must be skipped when there is no safe viewpoint. An open
capture is stored per workspace and restored after leaving and reopening the screen.

Every uploaded exterior frame records its facade section and available device-motion
orientation. GPS, when a future adapter supplies it, is metadata only and is never used
as centimetre geometry. The current Expo camera path does not capture depth, so the user
must enter one measured maximum building/facade dimension before reconstruction. The API
rechecks all four sections, frame orientation and the scale source before accepting the
job. T-233 is still required for section-aware multi-view reconstruction and merging.

## Apple Pencil (F-060)

`react-native-gesture-handler` reports stylus pressure and tilt separately from touch, so
the viewport treats a pencil as its own pointer type: it shows pressure in the HUD and
keeps taps precise instead of treating them as an orbit. Test on an iPad with a Pencil; a
finger and a mouse (web) go through the same handlers.
