# Test fixtures

Binary fixtures live here when generating them at test time would need a tool the test
environment does not have.

| File | What it is | How it was made |
| --- | --- | --- |
| `box.step` | 30 × 20 × 10 mm solid box, AP214, millimetres | OCCT `STEPControl_Writer` 7.8.1 |
| `box.iges` | the same box, IGES BRep mode, millimetres | OCCT `IGESControl_Writer` 7.8.1 |
| `blender_static_mesh.abc` | transformed static box with vertex normals and face-varying UVs, Ogawa storage | Blender 4.5.3 LTS native Alembic exporter |

Both were written by Open CASCADE itself inside the geometry-service build image, so they
are representative of what a CAD package exports rather than hand-rolled approximations.
To regenerate, compile a few lines against the OCCT in that image:

```cpp
BRepPrimAPI_MakeBox box(30.0, 20.0, 10.0);
STEPControl_Writer writer;                 // or IGESControl_Writer("MM", 1)
writer.Transfer(box.Shape(), STEPControl_AsIs);
writer.Write("box.step");
```

Mesh fixtures are generated in `tests/fixtures.py` at test time, because trimesh is
already a dependency.

The Alembic fixture is binary because the worker intentionally has no native Alembic SDK.
It was exported at frame 1 with Blender's `bpy.ops.wm.alembic_export`, `uvs=True`,
`normals=True`, and an object translation `(3, 4, 5)` plus scale `(2, 1, 1)`. Its source
box is 2 × 4 × 1 units, so applying the object transform yields bounds
`(1, 2, 4.5)..(5, 6, 5.5)` after Alembic Y-up is converted back to platform Z-up.
