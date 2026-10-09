# T-248 — curved mesh-to-CAD profile recovery (design)

Status: design only, no code. Follows T-247 (`05c7ea3`, selected connected planar mesh
region → exact sketch) and reuses the exact-analytic-geometry precedent of T-245/T-246
(rational NURBS sketch curves / surfaces, `493d961` / `6824ac1`).

## 0. What T-247 actually built (why this isn't a kernel-first feature)

T-247 added **no C++ kernel code**. The entire face-region analysis — connectivity,
coplanarity, manifoldness, single-outer-loop, collinear-corner simplification — lives in
`packages/contracts/src/topology.ts` (the function backing `CadProfileResult`, roughly
lines 460–673), which is shared by web/desktop/mobile. It is pure, synchronous, and
produces a `CadProfileSeed` (a `sketch` profile + origin/normal/x_direction). That seed is
then submitted as an ordinary operation (`extrude`/`loft`/`sweep`/`revolve` with a
`kind: "sketch"` profile) through `edits.build_replacement_plan` →
`manual_edit` job → the kernel — paths that already existed for T-243/T-244/T-245. The
kernel never sees the mesh; it only ever re-validates a sketch/profile contract it already
understood.

This matters for scoping: the **hard, new part of T-248 is not kernel work**, it is (a) a
bounded, closed-form fitting algorithm in `topology.ts` that can tell, from mesh geometry
alone, "this region is exactly a cylinder/cone/sphere lateral patch" and reject everything
else, and (b) one new kernel operation type that can build a **trimmed** analytic surface
and thicken it, because T-246's `nurbs_surface` only builds an **untrimmed rectangular**
patch (`BRepBuilderAPI_MakeFace(surface, tolerance)` with no wire — see
`services/geometry/src/kernel.cpp:788-801`).

## 1. Precise scope boundary

**In scope for this increment:**

A single connected, non-manifold-free, single-outer-loop (no holes) mesh face selection
whose geometry is, within a derived tolerance, an exact **elementary analytic surface** of
one of three families already native to OCCT and already parameterised by the kernel's
existing `Axis`/origin/radius vocabulary (`CreateCylinder`, `CreateCone`, `CreateSphere`):

- **Cylindrical** lateral patch (`Geom_CylindricalSurface`)
- **Conical** lateral patch (`Geom_ConicalSurface`)
- **Spherical** patch (`Geom_SphericalSurface`)

bounded by a closed trim loop that is **axis-aligned in the surface's own (u, v) parameter
space** — i.e. every boundary edge is either a pure generatrix (constant angle, cylinder/cone)
or meridian (constant angle, sphere), or a pure parallel (constant height/latitude circle).
This is the curved analogue of T-247's "outer loop of straight mesh edges": instead of a
planar polygon we recover a *rectilinear-in-parameter-space* curved quadrilateral-ish loop.

**Out of scope, deferred to later increments (state explicitly to the user when rejecting):**

- **Toroidal patches.** A torus fit is a genuinely non-linear, iterative least-squares
  problem (no closed form); cylinder/cone/sphere all have closed-form fits (§3). Deferred
  until a bounded-iteration solver with a hard convergence contract is designed on its own.
- **Free-form / generic NURBS surface fitting** from mesh samples (the literal "best-fit a
  B-spline surface to a point cloud" problem). This is a different, open-ended numerical
  problem — see the product question in §6. This increment reconstructs only surfaces that
  belong to a known, closed-form-checkable analytic family; it never invents control points.
- **Non-axis-aligned ("diagonal") trims** on a curved surface — e.g. a helical or freeform
  cut through a cylinder. Rejected with a dedicated reason, not approximated.
- **Holes** in a curved region (multi-loop boundary) — rejected, same as T-247's planar case.
- **Multi-patch stitching** (several adjacent curved/planar regions recovered as one
  B-Rep with shared edges) — still rejected as `selection_disconnected` or handled by
  repeating the single-patch flow once per connected region; no cross-patch topology
  reconciliation in this increment.
- **Periodic NURBS surfaces as a first-class kernel primitive** — not needed: OCCT's
  elementary surfaces (`Geom_CylindricalSurface` etc.) are natively periodic in u and exact
  by construction, so this increment satisfies the "periodic" half of
  `docs/IN_PROGRESS.md`'s "periodic/trimmed/multi-patch" wording without adding periodic
  B-spline knot handling to `NurbsSurface`.

This scope is deliberately narrower than the full F-001 ambition ("Mesh → parametric CAD:
распознавание плоскостей, цилиндров, отверстий, фасок, резьб, симметрии и повторов",
`docs/v2/v1_core/FEATURE_REGISTRY.txt:37-41`) but is the next *honest* increment: it adds
cylinders/cones/spheres to the "plane" T-247 already covers, in the same
exact-or-reject style, without crossing into fillets/threads/pattern-recognition/
approximate reconstruction.

## 2. The strict operation contract

New operation type `analytic_surface_patch`, modeled directly on `NurbsSurface`
(`services/api/app/geometry/operations.py:511-569`) and the arbitrary-plane contract of
`Extrude` (`_validate_profile_frame`, same file, lines 38-47).

```
AnalyticSurfacePatch(OperationBase):
  type: Literal["analytic_surface_patch"]
  surface: CylindricalSurface | ConicalSurface | SphericalSurface   # discriminated on "kind"
  boundary_uv: list[Vec2]      # 3..128 points, closed loop, NOT closing-duplicate
  thickness_mm: Positive
  tolerance_mm: float, gt=0, le=0.1, default 1e-5     # same bound as NurbsSurface
```

`CylindricalSurface`:
```
kind: Literal["cylinder"]
origin_mm: Vec3
axis_direction: Vec3          # must normalise to unit length within 1e-9
reference_direction: Vec3     # must normalise to unit length within 1e-9; ⟂ axis_direction
                              # (reuse _validate_profile_frame's orthogonality check verbatim)
radius_mm: Positive
```

`ConicalSurface`:
```
kind: Literal["cone"]
origin_mm: Vec3               # apex-side reference point, radius = radius_mm there
axis_direction: Vec3          # unit, as above
reference_direction: Vec3     # unit, ⟂ axis_direction
radius_mm: Positive           # radius at origin_mm (v = 0)
half_angle_deg: float, gt=0, lt=90   # strict — 0 degenerates to cylinder, 90 is a plane
```

`SphericalSurface`:
```
kind: Literal["sphere"]
center_mm: Vec3
polar_axis_direction: Vec3    # unit; defines v = latitude from pole
reference_direction: Vec3     # unit; ⟂ polar_axis_direction; defines u = 0
radius_mm: Positive
```

`boundary_uv` field-by-field rules (validated independently in Python **and** C++, same
"never trust the API layer alone" rule T-246 already follows):

- 3..128 points (bounded list size, same ceiling as T-247's 128-corner sketch loop).
- u ∈ [0, 2π) for cylinder/cone/sphere (periodic — a point with u outside this half-open
  range is rejected rather than silently wrapped); v is unbounded for cylinder/cone
  (axial position relative to `origin_mm`), v ∈ [-π/2, π/2] for sphere (latitude).
- The loop is closed implicitly (last point connects back to the first); an explicit
  duplicate closing point is rejected (`"boundary_uv must not repeat its closing point"`),
  mirroring how `PolygonProfile`/sketch loops are already specified elsewhere.
- **Axis-alignment rule** (the core new invariant): for every consecutive pair of boundary
  points, either their `u` values are equal within `tolerance_mm`-scaled epsilon (a
  generatrix/meridian edge) **xor** their `v` values are equal within the same epsilon (a
  parallel edge) — never both equal (zero-length edge, rejected) and never both different
  (a diagonal trim, rejected: this is exactly the "non-axis-aligned" boundary this
  increment refuses to approximate). The epsilon is `max(tolerance_mm, 1e-9)` in parameter
  units, consistent with how T-247 derives its planarity tolerance from the shape's own
  scale rather than a bare literal.
- A u-edge that crosses the periodic seam (e.g. u goes from 350° to 10°) is legal exactly
  once per loop and must be the shorter angular path (< π); a second seam crossing makes
  the loop self-overlapping and is rejected (`"boundary_uv crosses the periodic seam more
  than once"`).
- No self-intersection in (u, v) (reuse the same "collinear/degenerate edge" style check
  already used for sketch simplification, generalised to 2D segment intersection).
- Total swept angular range (sum of signed u-deltas around the loop) must be in
  `(0°, 360°]`; exactly `360°` is a full revolution (legal: a closed cylindrical shell
  band), `0°` or negative means a degenerate/self-cancelling loop (rejected).
- `thickness_mm`, `tolerance_mm`: identical bounds to `NurbsSurface` (`Positive`,
  `gt=0, le=0.1`) — no new precision policy invented.

## 3. Fail-closed behaviour spec

All rejection happens **before a job is enqueued** wherever geometrically decidable
without a job (client-side fit, then API-side contract validation), and **again,
independently, in C++** for anything the contract itself encodes (bounds, orthogonality,
axis-alignment, loop closure) — the kernel never trusts that the API already checked.

**Client-side (`topology.ts`), reused verbatim from T-247 — same codes, same meaning:**

| Code | Condition |
|---|---|
| `selection_empty` / `selection_too_large` / `face_missing` | unchanged from T-247 |
| `selection_disconnected` | selected faces are not one connected component |
| `selection_non_manifold` | an edge is shared by more than two selected faces |
| `selection_open_boundary` | a boundary vertex doesn't have exactly two boundary-edge neighbours |
| `selection_has_holes` | the boundary walk doesn't close into exactly one simple loop |

**Client-side, new to T-248 (the curved-fit path, only entered when the planar check at
T-247's `selection_non_planar` branch fails — i.e. this increment is additive, it does not
touch the planar path at all):**

| Code | Condition |
|---|---|
| `fit_axis_underdetermined` | the 3×3 covariance of face normals has no eigenvalue gap clearly separating one null direction from the other two (closed-form symmetric eigendecomposition — see §4 — not "no solution found" but "solution not distinguishable from noise") |
| `fit_not_single_analytic_surface` | none of the three closed-form fits (cylinder, cone, sphere — tried in that order, cheapest/most-constrained first) brings the max point-to-surface residual under the derived tolerance (see §4 for the tolerance formula); covers free-form, saddle, torus, and genuinely multi-patch-looking-like-one-patch regions |
| `boundary_not_axis_aligned` | after projecting the boundary loop into the fitted surface's (u, v) space, some edge is neither constant-u nor constant-v within tolerance |
| `boundary_crosses_seam_twice` | the periodic u-seam is crossed more than once |
| `boundary_too_complex` | boundary_uv would exceed 128 points |
| `profile_too_small` | fitted radius (or cone half-angle) is degenerate relative to tolerance, or the swept angular range rounds to ≤ 0 |

Every code above ships with a localized, specific message (mirroring
`ExactCadPanel.tsx`'s `profileFailure` map, `apps/web/src/components/ExactCadPanel.tsx:147-157`)
— never a generic "could not convert" string.

**Kernel-side (C++), independent re-validation — structured `PlanError`/`KernelError`,
following `nurbs_surface_failed`'s precedent (`services/geometry/src/kernel.cpp:788-810`,
`services/api/app/jobs/kernel_exec.py:89-92`):**

- Parse-time (`plan.cpp`, throws `PlanError`, same tier as `_validate_clamped_nurbs_basis`):
  malformed discriminant, non-unit axis/reference/polar vectors, non-orthogonal
  axis/reference pair, `half_angle_deg` outside `(0, 90)`, `boundary_uv` outside 3..128,
  non-axis-aligned edge, seam crossed twice, swept range outside `(0°, 360°]`.
- Execution-time (`kernel.cpp`, `ctx.fail(code, message)`):
  - `analytic_surface_patch_failed` — the elementary surface + wire could not form a
    bounded `TopoDS_Face` (`BRepBuilderAPI_MakeFace` not done), or
    `BRepOffsetAPI_MakeThickSolid` did not produce a valid shape.
  - Every result is re-validated as exactly one non-null, non-degenerate solid
    (`BRepGProp::VolumeProperties`, reverse on negative mass, same as every other
    creator) before it is accepted into `ctx.bodies`.
- `user_safe_kernel_message` gains one new entry, phrased like `nurbs_surface_failed`'s:
  *"The curved patch's trim loop could not form a valid thickened surface; check that its
  boundary follows the surface's axis and circles, and use a smaller thickness."*

Nothing in this feature ever falls back to an approximate shape: every one of the above
conditions is a **hard reject with a reason**, matching T-247's and T-246's existing
"never approximate" guarantee.

## 4. The fit algorithm (client-side, bounded, closed-form — point 4 of the procedure)

This is new relative to every prior T-24x increment (T-245/T-246 validate an
already-exact user- or AI-authored basis; nothing before T-248 *infers* geometry from
noisy samples). The explicit trust boundary:

> **This is "exact recovery of originally-exact curved geometry that got meshed," not
> "best-fit approximation of organic/noisy mesh."** It only succeeds when the mesh really
> is a tessellation of a cylinder/cone/sphere to begin with. It is explicitly not a general
> reverse-engineering tool for organic/scanned/noisy surfaces — see §6.

Given that framing, every fit step below is **closed-form** (a direct linear-algebra
solution), not an iterative optimizer — so there is no "max iterations" knob and no
convergence question to adjudicate; there is only a single residual check against a
tolerance derived from the mesh's own triangulation scale, same philosophy as T-247's
`tolerance = Math.max(toleranceMm, diagonal * 1e-6, 1e-7)` (`topology.ts:495`):

1. **Axis estimation.** For a cylinder/cone, every face normal is perpendicular to the
   axis. Build the 3×3 covariance matrix `C = Σ nᵢnᵢᵀ` over selected-face normals; its
   eigenvector of *smallest* eigenvalue is the candidate axis (closed-form 3×3 symmetric
   eigendecomposition — a fixed, non-iterative analytic formula for 3×3 exists and is used
   here, not a generic iterative solver). Reject (`fit_axis_underdetermined`) if the two
   smallest eigenvalues are not well separated from the largest by a fixed relative margin
   (e.g. smallest < 0.1 × largest) — this is the sphere/near-planar ambiguity guard.
2. **Cylinder fit.** Project all boundary+interior vertices onto the plane ⟂ axis through
   their centroid; fit a 2D circle through the projected points with the closed-form Kåsa
   algebraic circle fit (a single linear least-squares solve, no iteration) → origin,
   radius. Residual = max projected-point distance from the fitted circle.
3. **Cone fit.** If the cylinder residual exceeds tolerance, try: radius as a function of
   axial position should be affine, `r(z) = r₀ + k·z`; a single linear regression
   (closed-form) over `(z, r)` pairs gives `r₀, k`; `half_angle = atan(k)`. Residual = max
   deviation of actual radius from the fitted line.
4. **Sphere fit.** If both above fail: closed-form linear sphere fit (the standard
   "expand `|p-c|²=R²`" linearisation into one 4×4 linear solve) over all selected
   vertices → center, radius. Residual = max `| |p-c| - R |`.
5. **Tolerance derivation.** Rather than a bare constant, the accepted residual is derived
   from the mesh's own chordal-deviation-at-this-tessellation-density: for a circle of
   candidate radius `R` tessellated with average boundary edge angular step `Δθ` (computed
   from the actual sample), the expected chordal deviation is `R·(1 - cos(Δθ/2))` — a
   closed-form geometric fact, not a tuned magic number. The fit is accepted only if the
   measured residual is within a small constant factor (e.g. 3×) of this expected
   deviation; anything larger means the mesh isn't really a tessellation of that primitive.
6. **Boundary classification.** Map each boundary-loop vertex (already extracted by
   T-247's existing single-loop walk — reused unchanged) into the fitted surface's (u, v):
   `u = atan2(projected_y, projected_x)` relative to `reference_direction`, `v = axial
   offset` (cylinder/cone) or `v = asin(...)` (sphere latitude). Walk consecutive pairs;
   each must be constant-u or constant-v within the same tolerance family as step 5,
   else `boundary_not_axis_aligned`.
7. **No path ever returns a shape when a residual check fails** — only `{ ok: false, code
   }`, same discriminated-union result shape T-247 already established
   (`CadProfileResult`).

## 5. Touch list

Mirrors the exact file set T-246 touched for `nurbs_surface` (verified via
`grep -rl nurbs_surface`), plus the mesh-analysis files T-247 touched for its client-side
fit:

| File | Change |
|---|---|
| `services/geometry/src/plan.hpp` | Add `CylindricalSurface`/`ConicalSurface`/`SphericalSurface` structs, `AnalyticSurfacePatch` struct (`boundary_uv: vector<Vec2>`, `thickness_mm`, `tolerance_mm`), add to `OperationBody` variant |
| `services/geometry/src/plan.cpp` | Parse + independently re-validate every bound in §2/§3 (orthogonality, unit length, half-angle range, boundary size/closure/axis-alignment/seam, swept-angle range) |
| `services/geometry/src/kernel.cpp` | New `run(const Context&, const AnalyticSurfacePatch&)`: build `Geom_CylindricalSurface`/`Geom_ConicalSurface`/`Geom_SphericalSurface`, build a 2D wire from `boundary_uv` on the surface's parametric domain, `BRepBuilderAPI_MakeFace(surface, wire, true)`, `BRepOffsetAPI_MakeThickSolid::MakeThickSolidBySimple`, validate one non-null solid, orient by volume sign — same shape as the existing `NurbsSurface` `run()` (`kernel.cpp:757-811`) |
| `services/geometry/tests/test_kernel.cpp` | Golden tests, §6 below, plus a malformed-boundary (`boundary_not_axis_aligned`-equivalent C++ rejection) test mirroring `test_nurbs_surface`'s `malformed_refused` case |
| `services/api/app/geometry/operations.py` | `CylindricalSurface`/`ConicalSurface`/`SphericalSurface` Pydantic models (discriminated union on `kind`), `AnalyticSurfacePatch(OperationBase)` with all §2 `model_validator`s (reuse `_validate_profile_frame` for axis/reference orthogonality), add to the operation union |
| `services/api/app/services/edits.py` | Add `"analytic_surface_patch"` to the `_final_bodies` creators set (`edits.py:62-73`) |
| `services/api/app/jobs/kernel_exec.py` | Add `"analytic_surface_patch_failed"` to `user_safe_kernel_message` (`kernel_exec.py:69-96`) |
| `services/api/app/ai/contract.py` | Extend the creator-vocabulary list and add a paragraph describing `analytic_surface_patch` the same way `nurbs_surface` is described (`contract.py:143,208`) |
| `services/api/app/services/entitlements.py` | Add `"analytic_surface_patch"` to the same tier list `"nurbs_surface"` is in (`entitlements.py:51`) — see open question in §6 on whether the tier should differ |
| `services/api/tests/test_operations_schema.py` | Valid/malformed schema cases for the new operation |
| `services/api/tests/test_entitlements.py`, `services/api/tests/integration/test_entitlements_api.py` | Tier-denial tests |
| `services/api/tests/integration/test_edits_api.py` | API → job → operation-log integration test: submit a hand-authored `analytic_surface_patch` op through `replace_history`, assert the resulting version/body/provenance, same style as T-247's planar-profile integration tests added in that commit |
| `packages/contracts/operation-plan.schema.json` | Regenerated from the Python models — never hand-edited |
| `packages/contracts/src/operation-plan.ts` | Hand-authored TS mirror of `CylindricalSurface`/`ConicalSurface`/`SphericalSurface`/`AnalyticSurfacePatch`, matching how `NurbsSurface`'s TS type already mirrors its Pydantic model |
| `packages/contracts/src/client.ts` | Export wiring for the new operation type, same one-line addition pattern as T-247's `client.ts` diff |
| `packages/contracts/src/topology.ts` | The core new logic: axis covariance fit, cylinder/cone/sphere closed-form fits, tolerance derivation, boundary (u,v) classification; extend `CadProfileFailureCode` with the six new codes from §3; extend the seed result type (new discriminated member, e.g. `AnalyticCadProfileSeed`, alongside the existing planar `CadProfileSeed`) |
| `packages/contracts/test/topology.test.ts` | Unit tests: synthetic tessellated cylinder/cone/sphere patches recover known axis/radius/angle within tolerance; saddle/torus/free-form mesh → `fit_not_single_analytic_surface`; diagonal trim → `boundary_not_axis_aligned`; holed/disconnected curved region → existing T-247 codes still fire first |
| `apps/web/src/components/MeshEditPanel.tsx` | When the planar check fails, attempt the curved fit; on success show the recovered surface kind + radius/angle to the user before offering "Use as curved CAD patch" |
| `apps/web/src/components/ExactCadPanel.tsx` | New entries in the `profileFailure` message map for the six new codes; new accept path for an `AnalyticCadProfileSeed` alongside the existing planar one (`ExactCadPanel.tsx:147-190`) |
| `apps/web/src/components/OperationStackPanel.tsx` | Display `analytic_surface_patch` in the operation stack list, same one-line addition as `nurbs_surface` already required |
| `apps/web/src/app/projects/[id]/page.tsx` | Wiring to pass the new seed type through to the panels, same file T-247 touched |
| `docs/IN_PROGRESS.md` / `docs/IMPLEMENTED.md` | Move the entry once shipped, per the repo's existing process (not touched during design) |

No mobile-panel work: mobile CAD panels are already a separate, explicitly deferred item
per `docs/IN_PROGRESS.md` ("Ближайший клиентский остаток — перенос... панелей в mobile").

## 6. Proof plan

**OCCT golden tests (`services/geometry/tests/test_kernel.cpp`), same style as
`test_nurbs_surface` (volume/topology/validity on a known exact shape):**

1. **Cylindrical wedge band.** A cylinder of radius 10 mm, axis = Z, a 90°-wide,
   20 mm-tall lateral band (`boundary_uv` = a rectilinear rectangle in (u, v): two
   generatrices 90° apart × two parallels 0 and 20 mm), thickened by 2 mm outward.
   Closed-form expected volume: a quarter-annulus extruded 20 mm,
   `V = (π/4)·(12² − 10²)·20 = 220π mm³` — note this is the **same volume as T-246's
   quarter-cylinder NURBS-surface golden test**, which is deliberate: it proves the new
   analytic-surface path and the existing rational-NURBS path agree exactly on a shape
   both can represent, giving a cross-check between T-246 and T-248 rather than just an
   isolated new number.
2. **Conical frustum lateral band.** A cone with `radius_mm = 10` at `origin_mm`,
   `half_angle_deg = 30`, a full 360° band from `v=0` to `v=20` thickened by 2 mm — proves
   the full-revolution (seam-crossing-once) boundary path and the non-cylindrical radius
   law, with expected volume computed from the frustum lateral-shell formula and checked
   against OCCT's own `BRepGProp::VolumeProperties` to a tolerance of `1e-5`, matching
   every other golden test's tolerance in this file.
3. **Spherical cap patch.** A sphere of radius 10 mm, a polar cap from `v=0` to
   `v=30°` latitude, full 360° in u, thickened by 2 mm inward — proves the sphere branch
   and a seam-crossing-once full-revolution loop on a different surface family.
4. **Malformed-boundary rejection (C++ boundary).** Same `boundary_uv` as test 1 but with
   one corner's `v` nudged so the edge is neither constant-u nor constant-v — assert
   `geo::parse_plan` throws `PlanError`, mirroring `test_nurbs_surface`'s
   `malformed_refused` assertion. This proves the kernel re-validates axis-alignment
   independently of whatever the API already checked.
5. **`set_parameter` replay.** Re-run test 1 then replay `thickness_mm` to a different
   value via `set_parameter`, same pattern as `test_nurbs_surface`'s `thinner` case —
   proves the new operation participates correctly in the existing replay/edit machinery
   without special-casing.

**`packages/contracts/test/topology.test.ts` (fit correctness, the genuinely new risk):**

6. Programmatically tessellate a cylinder/cone/sphere of known axis, origin, radius
   (or half-angle) at a few different triangle densities; feed the resulting
   `MeshTopology` + a face selection through the new fit function; assert the recovered
   parameters match the known ground truth within the tolerance formula of §4 step 5, and
   that the recovered `boundary_uv` round-trips back through the kernel-side validator.
7. Negative cases: a saddle-shaped (hyperbolic paraboloid) mesh patch → `fit_not_single_analytic_surface`;
   a cylinder patch with one boundary edge cut on the diagonal → `boundary_not_axis_aligned`;
   a torus patch → `fit_not_single_analytic_surface` (explicitly proving torus stays
   out of scope rather than silently misfitting as a sphere/cylinder); a selection that
   is curved but has a second, disconnected island → `selection_disconnected` (proves the
   T-247 checks still run first, unchanged, ahead of the new fit).

**Everything else unchanged from the repo's existing gate, run exactly as for T-246/T-247:**
schema tests (valid/malformed `analytic_surface_patch`), integration tests
(API → job → operation log, tier denial, `replace_history` immutable-child flow),
production OCCT Docker build with `-Werror` + CTest, contracts/web typecheck + build, full
API/worker suites, `git diff --check`.

## 7. Open questions requiring a product/owner decision

1. **Is approximate/best-fit curved recovery ever wanted?** This design deliberately
   refuses to fit anything that isn't provably (within tessellation-derived tolerance) a
   cylinder/cone/sphere — e.g. a scanned organic/freeform surface will always get
   `fit_not_single_analytic_surface`, never a "close enough" NURBS patch. If the product
   wants a *separate*, clearly-labeled "best guess, not exact" reconstruction mode (closer
   to Polycam/KIRI's retopology features, referenced in
   `docs/COMPETITOR_UI_ANALYSIS.md`), that is a different feature with a different trust
   contract (it could never honestly claim the "exact" badge T-247/T-245/T-246 all carry)
   and needs an explicit product decision before any design work starts on it.
2. **Entitlement tier.** Should `analytic_surface_patch` sit in the same tier as
   `nurbs_surface` (currently Pro, `entitlements.py:51`), or does recognising "this mesh
   region is a cylinder" belong in a lower tier than hand-authoring a rational NURBS patch,
   since it's arguably a more basic/expected capability (plain cylinder recognition is the
   first bullet of the F-001 reverse-engineering feature group)? Needs an owner call.
3. **Torus timeline.** Torus is common enough (fillets, rounded handles, O-ring grooves)
   that it's likely the very next ask after this ships. Worth deciding now whether it's the
   immediately-following increment (needs its own bounded-iteration design, since torus
   fitting has no closed form) or sits behind other priorities.
4. **Multi-patch stitching UX.** Even without cross-patch topology reconciliation, should
   the UI let a person run this flow once per connected region and manually assemble the
   results with existing `boolean`/`fillet` operations, or should "select several regions
   at once" be explicitly blocked until real multi-patch stitching exists? Affects
   `MeshEditPanel.tsx` UX scope, not the kernel contract.
