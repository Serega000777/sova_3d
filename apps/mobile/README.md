# Mobile app (F-058)

Expo SDK 57 / React Native 0.86, iOS + Android including iPad. Everything here is
JS-only, so **the whole app runs in Expo Go** — the constitution (§2a) makes that the
main manual-testing route, and nothing in the product path may depend on a custom build.

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
| LiDAR / ARCore depth + camera pose (T-076/T-077) | no | yes, once the native module is built |

The capability probe (`src/capabilities.ts`, T-074) keeps depth scanning off until a
native capture path is wired and validated. The scan screen always labels current
captures as RGB photos and explains the missing LiDAR mode.

### The depth-scan boundary

`ScanSession.mode` is `rgb` (photos, works everywhere) or `rgb_depth` (ARKit/ARCore depth
and pose). The API, the job and the reconstruction adapters already take poses and depth
frames — `POST /scans/{id}/frames` accepts `kind: "depth"` and a `pose` object — so adding
the native module needs client-side integration with the existing protocol. Until it exists
in a development build, `probe().depthScan` is false and the scale of a scan is reported as
`assumed` unless the user gives a size.

## Apple Pencil (F-060)

`react-native-gesture-handler` reports stylus pressure and tilt separately from touch, so
the viewport treats a pencil as its own pointer type: it shows pressure in the HUD and
keeps taps precise instead of treating them as an orbit. Test on an iPad with a Pencil; a
finger and a mouse (web) go through the same handlers.
