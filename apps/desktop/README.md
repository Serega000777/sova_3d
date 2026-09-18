# Desktop shell (T-086, F-057)

A Tauri 2 window around the web workspace, for **Windows and macOS**.

The workspace UI is `apps/web` — one implementation, not a fork. The shell adds what a
browser tab cannot: a real application window and a remembered workspace address. Later
it is also where genuinely local work belongs (large imports, offline caches).

## Run it

```bash
pnpm --filter @physical-ai/desktop dev
```

`tauri dev` starts the web client on <http://localhost:3100> and opens it in the window,
with hot reload. Point the API somewhere else with `NEXT_PUBLIC_API_URL`.

## Bundle it

```bash
pnpm --filter @physical-ai/desktop bundle
```

Bundles are per-OS: run it on Windows for `.msi`/NSIS and on macOS for `.app`/`.dmg`
(there is no cross-compilation). CI compiles the shell on both.

The bundled app opens `launcher/index.html`, which asks for the workspace address
(default <http://localhost:3100>) and navigates the window there; the choice is saved in
the app's config directory. To ship an app that goes straight to your deployment,
override the launcher at build time:

```bash
pnpm --filter @physical-ai/desktop bundle --config '{"build":{"frontendDist":"https://app.example.com"}}'
```

## Prerequisites

- Rust (stable) via [rustup](https://rustup.rs)
- Windows: Visual Studio Build Tools with the MSVC toolchain + Windows SDK, and WebView2
  (preinstalled on Windows 11)
- macOS: Xcode command line tools (`xcode-select --install`)

## Security

A workspace loaded over http(s) is a remote origin: the capability file grants it no
desktop APIs at all (`remote.urls` is empty), so the page in the window is just a web
page. Only the bundled launcher can call `workspace_url` and `open_workspace`.

## Icons

`src-tauri/icons/` is generated from `app-icon.png`:

```bash
pnpm --filter @physical-ai/desktop exec tauri icon ./app-icon.png
```
