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

Sign in with the token and workspace id printed by:

```bash
docker compose -f infra/docker-compose.yml exec api uv run --no-sync python -m app.cli create-user
```

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

The capability probe (`src/capabilities.ts`, T-074) decides this at runtime: it looks the
native scanner up rather than importing it, so a missing module is a feature that is off,
never a crash at startup. The scan screen says which mode it is in.

### The depth-scan boundary

`ScanSession.mode` is `rgb` (photos, works everywhere) or `rgb_depth` (ARKit/ARCore depth
and pose). The API, the job and the reconstruction adapters already take poses and depth
frames — `POST /scans/{id}/frames` accepts `kind: "depth"` and a `pose` object — so adding
the native module is a client-side change, not a protocol change. Until that module exists
in a development build, `probe().depthScan` is false and the scale of a scan is reported as
`assumed` unless the user gives a size.

## Apple Pencil (F-060)

`react-native-gesture-handler` reports stylus pressure and tilt separately from touch, so
the viewport treats a pencil as its own pointer type: it shows pressure in the HUD and
keeps taps precise instead of treating them as an orbit. Test on an iPad with a Pencil; a
finger and a mouse (web) go through the same handlers.
