# services/geometry

Deterministic CAD kernel (C++20 + Open CASCADE). Executes validated
OperationPlans (`packages/contracts/operation-plan.schema.json`); the LLM
never touches geometry directly.

```
geometry-service exec <plan.json> <out_dir> [--deflection MM]
geometry-service version
```

`exec` writes `<out_dir>/<body>.brep` and `<body>.stl` (binary, canonical mm)
for every surviving body and prints one JSON object: bbox, volume, area,
topology counts and a B-Rep validity flag per body, or a structured error
`{code, message, operation_id, operation_type}` (exit 1). Same plan ⇒
byte-identical outputs (checked by `tests/cli_determinism.sh`).

Operations: create_box, create_cylinder, extrude (rectangle/circle/polygon),
boolean cut/fuse/common, fillet, chamfer, add_hole (through or blind),
translate, rotate, set_dimensions, set_parameter (resolved by replaying the
plan). Faces/edges are chosen by geometric selectors, never kernel indices.

## Building

No local toolchain is needed: `docker build -t physical-ai-geometry .`
compiles against Debian trixie's OCCT 7.8.1 and runs the CTest suite
(golden volumes/topology per operation, structured errors, fixture plans,
CLI determinism). The worker image builds the same sources
(`services/api/Dockerfile`, stage `geometry-build`) and ships the binary on
`PATH`; `worker.geometry.execute_plan()` runs it under the sandbox limits.

The pack pins OCCT 8.0; 7.8.1 is what the distro provides today and the API
surface used here is unchanged between the two. Upgrade by vendoring an
8.x build into the `geometry-build` stage.
