# Architecture

Canonical engineering description is in [`01_ARCHITECTURE_STACK.docx`](01_ARCHITECTURE_STACK.docx).

Rule: LLM/VLM -> versioned OperationPlan -> deterministic geometry/mesh workers -> validators -> immutable ProjectVersion.

## Account tiers and entitlement boundary

SOVA starts with two account tiers: `free` and paid `pro`. UI complexity
(`simple`/`advanced`) is an independent preference inside the user's tier; changing the
editor mode never changes entitlements.

- **Free:** AI/photo/single-scan creation, basic primitives and transforms, dimensions,
  holes, print preparation, STL/3MF/GLB/FBX exports, and linear version history.
- **Pro:** everything in Free plus boolean/fillet/chamfer/shell/pattern/mirror operations,
  mesh/topology editing, reverse engineering, engineering advice and adaptation, fit tests,
  splitting into printable parts, STEP/IGES, game-ready export (LOD/UV/PBR/collider), and
  rollback or comparison of saved versions.
- Project-start choices remain discoverable to every user. The operation/export actually
  requested is what determines whether Pro is required.

`User.plan` is the effective entitlement value. A future billing adapter changes that value
when a subscription starts, renews, expires, or is cancelled. Every material paid action is
checked in the API (and AI-produced plans are checked before kernel execution); client locks
are explanatory UX only. Unknown/legacy tier values fail closed to Free. A rejected paid
action uses HTTP 402 with `pro_subscription_required`, the capability, current tier, and
required tier so web, mobile, and desktop can present one upgrade flow.

## Planned desktop delivery phase (after the current product blocks)

SOVA must be delivered not only as a website, but also as an installable desktop
product with functional parity and desktop-specific adaptation. The existing Tauri 2
shell in `apps/desktop` is the base for this phase; it is not yet the finished desktop
distribution.

### User delivery

- The public website provides a desktop download page, detects the visitor's OS, and
  offers the current stable installer plus release notes and supported-system details.
- Windows artifacts: signed `.exe` (NSIS) and/or `.msi` installers.
- macOS artifacts: signed and notarized `.dmg` containing the `.app` bundle (with a
  `.pkg` only if deployment requirements justify it).
- Every release publishes a version, checksum, channel (`stable` initially), and a
  rollback-capable update manifest. The app includes a signed auto-update path.

### Desktop product scope

- One shared product core and contracts across web and desktop; desktop UI may adapt
  navigation, windowing, keyboard shortcuts, drag-and-drop, file dialogs, filesystem
  access, notifications, and large local imports without forking business rules.
- Feature parity with the completed web service for project creation, scanning/import,
  AI workflows, editing, validation, export, accounts, consent, and feedback.
- The installer contains the desktop client and the local components required for PC
  workflows. Account, collaboration, durable project storage, billing, model-serving,
  and other centrally managed capabilities continue to use authenticated backend APIs;
  large-file staging, caches, and explicitly supported processing may run locally.
- Local data has an explicit storage location, quota/cleanup policy, encryption rules,
  migration strategy, and uninstall behaviour. Secrets never ship inside the bundle.
- Offline behaviour is declared per feature: cached projects and queued operations may
  work locally where supported; server-only operations fail explicitly and recover on
  reconnect.

### Release architecture and acceptance gate

- CI builds on native Windows and macOS runners; desktop packages are never treated as
  cross-compiled artifacts.
- Production release requires code signing, macOS notarization, installer smoke tests,
  clean install/upgrade/uninstall tests, antivirus/reputation checks, and verification
  of download checksums from the website.
- The download page and desktop updater consume the same signed release manifest so
  website, installer, and in-app version information cannot drift.
- Desktop releases are blocked until the current functional roadmap is complete and a
  dedicated desktop parity/security/UX acceptance pass succeeds on both operating
  systems.
