# Alembic import/export handoff — 2026-09-29

## Final status

F-014/F-015 now support a deliberately bounded **static Alembic Ogawa PolyMesh subset**.
This is not a complete Alembic implementation and does not depend on the native Alembic SDK or
HDF5.

Implemented import behavior:

- Ogawa archives containing `AbcGeom_PolyMesh_v1` objects.
- Positions, polygon indices/counts, hierarchy transforms, normals and UVs (including indexed
  geometry parameters and constant/uniform/vertex/varying/face-varying scopes).
- Polygon fan triangulation, Y-up to platform Z-up conversion, multiple static meshes, and mesh
  diagnostics through the existing sandboxed import path.
- The first geometry sample is read. Animated archives produce an `animation_ignored` warning.
- Defensive validation of offsets, declared sizes, property types/cardinalities, nesting, object
  counts, faces, vertices and triangles. Unfinalized, truncated and legacy HDF5 archives are
  rejected.

Implemented export behavior:

- One static `AbcGeom_PolyMesh_v1` object in a finalized Ogawa archive.
- Triangle topology, positions, vertex normals and vertex UVs.
- Platform Z-up is converted to Alembic Y-up. Coordinates remain in platform millimetres;
  Alembic has no standard unit declaration.
- Export is registered through the worker/API format registries and exposed by the conversion UI.

Not implemented:

- Time-varying geometry or transforms (only sample zero is imported; export is static).
- Skeletons, skinning, materials/textures, cameras, curves, points, SubD or NuPatch schemas.
- Legacy HDF5-backed Alembic archives.
- Preservation of arbitrary/custom Alembic properties or scene metadata.
- A general-purpose Alembic writer: output is one triangulated static mesh object.

## Fixes made while completing the WIP

- Updated an older importer regression test that still used `abc` as its example of an unsupported
  format; it now uses an actually unknown format.
- Added strict integer type validation for indexed UV/normal `.indices` arrays while retaining the
  unsigned 32-bit representation emitted by Blender.
- Prevented malicious face-count arrays from overflowing NumPy `int64` during topology validation;
  face count is bounded and totals are now calculated with Python integers before triangulation.
- Corrected strict typing around NumPy dtypes, trimesh concatenation/visuals and test helpers.

## Verification

Dependencies were installed with `uv sync` in `services/worker` and `uv sync --extra worker` in
`services/api`.

Focused Alembic test:

```text
============================== 5 passed in 3.92s ===============================
```

Final worker format/conversion regression run:

```text
100 passed, 5 skipped, 26 warnings in 46.30s
```

Command covered `test_alembic.py`, `test_exports.py`, `test_importers.py`,
`test_conversion_golden.py`, `test_malicious_inputs.py`, `test_cad_import.py`, `test_fbx.py` and
`test_web3d.py`. The five skips are OCCT-dependent CAD import tests; warnings are existing
pycollada/NumPy deprecations.

API format/import/export regression run:

```text
================= 25 passed, 1 skipped, 15 warnings in 29.98s ==================
```

The skip is the OCCT-dependent CAD upload test; warnings are existing dependency deprecations.

Static checks:

```text
worker: All checks passed!
worker: Success: no issues found in 64 source files
api:    All checks passed!
api:    Success: no issues found in 5 source files
```

These are `ruff` plus full worker `mypy worker tests`, and targeted API mypy checks for the changed
format/import paths and their tests.
