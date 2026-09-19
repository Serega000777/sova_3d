# Scanner bridge (F-082)

From a dedicated 3D scanner on the desk to a project in the workspace.

```bash
uv run --project tools/scanner-bridge physical-ai-scanner scan \
  --api http://localhost:18000 --token pai_... --workspace <workspace-id> \
  --driver folder --path "C:/Users/me/Documents/Revo Scan/exports" --label "bumper"
```

Drivers (`--driver`):

- `folder` — any scanner whose software saves fragments or the fused mesh as PLY/STL/OBJ
  (Revo Scan, Creality Scan, EXScan, Artec Studio…). Each new file is a fragment the moment
  it is fully written; a `<file>.json` beside it may carry the pose (`{"matrix": 4x4}` or
  `{"azimuth_deg": 45}`). The scan ends after `--idle` seconds without a new file.
- `realsense` — an Intel RealSense depth camera on a turntable (`uv sync --extra realsense`
  installs `pyrealsense2`). One point-cloud fragment per `--steps`; press Enter after each turn.
- `simulated` — a known 120 × 60 × 40 mm object in angular shells, for a first run without hardware.

Every fragment reaches the platform as it arrives, so the Scanner section
(`/scanner/<session>`) shows the model growing; when the device stops, the platform fuses the
fragments into one metric model and, unless `--no-accept`, adds it to the project.
