#include "kernel.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>
#include <optional>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_GTransform.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepFilletAPI_MakeChamfer.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepGProp.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepOffsetAPI_MakeOffsetShape.hxx>
#include <BRepOffsetAPI_MakeThickSolid.hxx>
#include <BRepOffset_Mode.hxx>
#include <GeomAbs_JoinType.hxx>
#include <TopTools_ListOfShape.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepTools.hxx>
#include <Bnd_Box.hxx>
#include <GProp_GProps.hxx>
#include <GeomAbs_CurveType.hxx>
#include <Precision.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <IGESControl_Controller.hxx>
#include <IGESControl_Reader.hxx>
#include <IGESControl_Writer.hxx>
#include <STEPControl_Writer.hxx>
#include <Interface_Static.hxx>
#include <STEPControl_Reader.hxx>
#include <ShapeFix_Shape.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <TopoDS_Compound.hxx>
#include <BRep_Builder.hxx>
#include <Standard_Failure.hxx>
#include <StlAPI_Writer.hxx>
#include <TopAbs_Orientation.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <gp_Ax1.hxx>
#include <gp_Ax2.hxx>
#include <gp_Circ.hxx>
#include <gp_Dir.hxx>
#include <gp_GTrsf.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>

namespace physical_ai::geometry {

namespace {

constexpr double kAngularTolerance = 1e-6;
constexpr double kThroughMargin_mm = 1.0;

gp_Dir dir_of(Axis axis) {
  switch (axis) {
    case Axis::X: return gp_Dir(1, 0, 0);
    case Axis::Y: return gp_Dir(0, 1, 0);
    case Axis::Z: return gp_Dir(0, 0, 1);
  }
  return gp_Dir(0, 0, 1);
}

int axis_index(Axis axis) { return axis == Axis::X ? 0 : axis == Axis::Y ? 1 : 2; }

// A non-uniform resize hands back B-spline geometry for what is still a flat face or a
// straight edge, so selectors test the shape, not the analytic type OCCT happens to keep.
constexpr double kFlatTolerance = 1e-5;
constexpr double kStraightTolerance_mm = 1e-4;

struct FacePlane {
  gp_Pnt point;   // a point on the face (its centroid)
  gp_Dir normal;  // surface normal, before orientation is applied
};

std::optional<FacePlane> face_plane(const TopoDS_Face& face) {
  BRepAdaptor_Surface surface(face);
  GProp_GProps props;
  BRepGProp::SurfaceProperties(face, props);
  if (surface.GetType() == GeomAbs_Plane) {
    return FacePlane{props.CentreOfMass(), surface.Plane().Axis().Direction()};
  }
  const double u0 = surface.FirstUParameter(), u1 = surface.LastUParameter();
  const double v0 = surface.FirstVParameter(), v1 = surface.LastVParameter();
  if (!std::isfinite(u0) || !std::isfinite(u1) || !std::isfinite(v0) || !std::isfinite(v1)) {
    return std::nullopt;
  }
  std::optional<gp_Dir> normal;
  for (int i = 0; i <= 2; ++i) {
    for (int j = 0; j <= 2; ++j) {
      const double u = u0 + (u1 - u0) * i / 2.0;
      const double v = v0 + (v1 - v0) * j / 2.0;
      gp_Pnt point;
      gp_Vec du, dv;
      surface.D1(u, v, point, du, dv);
      const gp_Vec cross = du.Crossed(dv);
      if (cross.Magnitude() <= Precision::Confusion()) continue;
      const gp_Dir here(cross);
      if (!normal) {
        normal = here;
      } else if (!here.IsEqual(*normal, kFlatTolerance)) {
        // IsParallel would accept a cylinder, whose opposite sides are antiparallel.
        return std::nullopt;  // genuinely curved
      }
    }
  }
  if (!normal) return std::nullopt;
  return FacePlane{props.CentreOfMass(), *normal};
}

std::optional<gp_Dir> straight_direction(const TopoDS_Edge& edge) {
  BRepAdaptor_Curve curve(edge);
  if (curve.GetType() == GeomAbs_Line) return curve.Line().Direction();
  const double first = curve.FirstParameter(), last = curve.LastParameter();
  if (!std::isfinite(first) || !std::isfinite(last)) return std::nullopt;
  const gp_Pnt a = curve.Value(first), b = curve.Value(last);
  if (a.Distance(b) <= Precision::Confusion()) return std::nullopt;
  const gp_Dir chord(gp_Vec(a, b));
  for (int i = 1; i < 8; ++i) {
    const gp_Pnt sample = curve.Value(first + (last - first) * i / 8.0);
    const double along = gp_Vec(a, sample).Dot(gp_Vec(chord));
    if (sample.Distance(a.Translated(gp_Vec(chord) * along)) > kStraightTolerance_mm) {
      return std::nullopt;
    }
  }
  return chord;
}

gp_Pnt pnt(const Vec3& v) { return gp_Pnt(v[0], v[1], v[2]); }

Bnd_Box bounds_of(const TopoDS_Shape& shape) {
  Bnd_Box box;
  BRepBndLib::AddOptimal(shape, box, false, false);
  return box;
}

BoundingBox to_bbox(const Bnd_Box& box) {
  BoundingBox out;
  if (box.IsVoid()) return out;
  box.Get(out.min_x, out.min_y, out.min_z, out.max_x, out.max_y, out.max_z);
  return out;
}

struct Context {
  const Operation& op;
  std::map<std::string, TopoDS_Shape>& bodies;

  [[noreturn]] void fail(const std::string& code, const std::string& message) const {
    throw KernelError{op.id, op.type, code, message};
  }

  TopoDS_Shape& body(const std::string& name) const {
    auto it = bodies.find(name);
    if (it == bodies.end()) fail("unknown_body", "no body named " + name);
    return it->second;
  }
};

// The outermost planar face whose outward normal is ±axis; ties broken by area.
TopoDS_Face find_face(const Context& ctx, const TopoDS_Shape& shape, const FaceByNormal& sel) {
  const gp_Dir wanted = sel.positive ? dir_of(sel.axis) : dir_of(sel.axis).Reversed();
  const int idx = axis_index(sel.axis);
  bool found = false;
  TopoDS_Face best;
  double best_offset = -1e300, best_area = -1;
  for (TopExp_Explorer exp(shape, TopAbs_FACE); exp.More(); exp.Next()) {
    const TopoDS_Face face = TopoDS::Face(exp.Current());
    const auto flat = face_plane(face);
    if (!flat) continue;
    gp_Dir normal = flat->normal;
    if (face.Orientation() == TopAbs_REVERSED) normal.Reverse();
    if (!normal.IsEqual(wanted, kFlatTolerance)) continue;
    const double offset = (sel.positive ? 1.0 : -1.0) * flat->point.Coord(idx + 1);
    GProp_GProps props;
    BRepGProp::SurfaceProperties(face, props);
    const double area = props.Mass();
    if (!found || offset > best_offset + 1e-9 ||
        (std::abs(offset - best_offset) <= 1e-9 && area > best_area)) {
      found = true;
      best = face;
      best_offset = offset;
      best_area = area;
    }
  }
  if (!found) {
    ctx.fail("no_face_selected", std::string("no planar face with normal ") +
                                     (sel.positive ? "+" : "-") + axis_name(sel.axis));
  }
  return best;
}

constexpr double kOuterTolerance = 1e-4;  // mm: an edge is on the box or it is not

std::vector<TopoDS_Edge> select_edges(const Context& ctx, const TopoDS_Shape& shape,
                                      const EdgeSelector& selector) {
  std::vector<TopoDS_Edge> edges;
  auto collect = [&](const TopoDS_Shape& scope) {
    for (TopExp_Explorer exp(scope, TopAbs_EDGE); exp.More(); exp.Next()) {
      edges.push_back(TopoDS::Edge(exp.Current()));
    }
  };
  std::visit(
      [&](const auto& sel) {
        using T = std::decay_t<decltype(sel)>;
        if constexpr (std::is_same_v<T, AllEdges>) {
          collect(shape);
        } else if constexpr (std::is_same_v<T, EdgesParallelTo>) {
          const gp_Dir axis = dir_of(sel.axis);
          const BoundingBox bb = to_bbox(bounds_of(shape));
          const int along = axis_index(sel.axis);
          const double extremes[3][2] = {{bb.min_x, bb.max_x}, {bb.min_y, bb.max_y}, {bb.min_z, bb.max_z}};
          for (TopExp_Explorer exp(shape, TopAbs_EDGE); exp.More(); exp.Next()) {
            const TopoDS_Edge edge = TopoDS::Edge(exp.Current());
            const auto direction = straight_direction(edge);
            if (!direction) continue;
            if (!direction->IsParallel(axis, kAngularTolerance)) continue;
            if (sel.outer) {
              // an outer edge sits at a bounding-box extreme on both of the other axes
              BRepAdaptor_Curve curve(edge);
              const gp_Pnt mid = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2);
              const double coords[3] = {mid.X(), mid.Y(), mid.Z()};
              bool on_boundary = true;
              for (int k = 0; k < 3; ++k) {
                if (k == along) continue;
                const bool at_min = std::abs(coords[k] - extremes[k][0]) < kOuterTolerance;
                const bool at_max = std::abs(coords[k] - extremes[k][1]) < kOuterTolerance;
                if (!at_min && !at_max) on_boundary = false;
              }
              if (!on_boundary) continue;
            }
            edges.push_back(edge);
          }
        } else if constexpr (std::is_same_v<T, EdgesOfFace>) {
          if (const auto* by_normal = std::get_if<FaceByNormal>(&sel.face)) {
            collect(find_face(ctx, shape, *by_normal));
          } else {
            collect(shape);
          }
        }
      },
      selector);
  if (edges.empty()) ctx.fail("no_edges_selected", "edge selector matched nothing");
  return edges;
}

TopoDS_Shape unify(const TopoDS_Shape& shape) {
  // Merge coplanar faces/collinear edges left behind by booleans so later
  // fillets and selectors see the same topology a human would draw.
  ShapeUpgrade_UnifySameDomain unifier(shape, true, true, true);
  unifier.Build();
  return unifier.Shape();
}

TopoDS_Shape make_profile_face(const Context& ctx, const Profile& profile, const Vec3& origin) {
  const gp_Pnt o = pnt(origin);
  return std::visit(
      [&](const auto& p) -> TopoDS_Shape {
        using T = std::decay_t<decltype(p)>;
        if constexpr (std::is_same_v<T, RectangleProfile>) {
          BRepBuilderAPI_MakePolygon poly;
          poly.Add(o);
          poly.Add(gp_Pnt(o.X() + p.width_mm, o.Y(), o.Z()));
          poly.Add(gp_Pnt(o.X() + p.width_mm, o.Y() + p.depth_mm, o.Z()));
          poly.Add(gp_Pnt(o.X(), o.Y() + p.depth_mm, o.Z()));
          poly.Close();
          return BRepBuilderAPI_MakeFace(poly.Wire()).Face();
        } else if constexpr (std::is_same_v<T, CircleProfile>) {
          gp_Circ circle(gp_Ax2(o, gp_Dir(0, 0, 1)), p.diameter_mm / 2.0);
          BRepBuilderAPI_MakeWire wire(BRepBuilderAPI_MakeEdge(circle).Edge());
          return BRepBuilderAPI_MakeFace(wire.Wire()).Face();
        } else {
          BRepBuilderAPI_MakePolygon poly;
          for (const auto& pt : p.points_mm) poly.Add(gp_Pnt(o.X() + pt[0], o.Y() + pt[1], o.Z()));
          poly.Close();
          if (!poly.IsDone()) ctx.fail("bad_profile", "polygon profile is degenerate");
          return BRepBuilderAPI_MakeFace(poly.Wire()).Face();
        }
      },
      profile);
}

void check_boolean(const Context& ctx, BRepAlgoAPI_BooleanOperation& op) {
  if (!op.IsDone() || op.HasErrors()) ctx.fail("boolean_failed", "kernel boolean did not complete");
  if (op.Shape().IsNull()) ctx.fail("boolean_failed", "boolean produced an empty result");
}

void run(const Context& ctx, const CreateBox& box) {
  gp_Pnt corner = pnt(box.origin_mm);
  if (box.centered) {
    corner = gp_Pnt(corner.X() - box.width_mm / 2, corner.Y() - box.depth_mm / 2,
                    corner.Z() - box.height_mm / 2);
  }
  ctx.bodies[ctx.op.id] =
      BRepPrimAPI_MakeBox(corner, box.width_mm, box.depth_mm, box.height_mm).Shape();
}

void run(const Context& ctx, const CreateCylinder& cyl) {
  gp_Ax2 axes(pnt(cyl.origin_mm), dir_of(cyl.axis));
  ctx.bodies[ctx.op.id] =
      BRepPrimAPI_MakeCylinder(axes, cyl.diameter_mm / 2.0, cyl.height_mm).Shape();
}

void run(const Context& ctx, const Extrude& ex) {
  const TopoDS_Shape face = make_profile_face(ctx, ex.profile, ex.origin_mm);
  ctx.bodies[ctx.op.id] = BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, ex.height_mm)).Shape();
}

void run(const Context& ctx, const Boolean& b) {
  TopoDS_Shape& target = ctx.body(b.target);
  const TopoDS_Shape tool = ctx.body(b.tool);
  TopoDS_Shape result;
  switch (b.op) {
    case BooleanOp::Cut: {
      BRepAlgoAPI_Cut op(target, tool);
      check_boolean(ctx, op);
      result = op.Shape();
      break;
    }
    case BooleanOp::Fuse: {
      BRepAlgoAPI_Fuse op(target, tool);
      check_boolean(ctx, op);
      result = op.Shape();
      break;
    }
    case BooleanOp::Common: {
      BRepAlgoAPI_Common op(target, tool);
      check_boolean(ctx, op);
      result = op.Shape();
      break;
    }
  }
  target = unify(result);
  ctx.bodies.erase(b.tool);  // consumed
}

void run(const Context& ctx, const Fillet& f) {
  TopoDS_Shape& target = ctx.body(f.target);
  BRepFilletAPI_MakeFillet maker(target);
  for (const auto& edge : select_edges(ctx, target, f.edges)) maker.Add(f.radius_mm, edge);
  maker.Build();
  if (!maker.IsDone()) ctx.fail("fillet_failed", "radius too large for the selected edges");
  target = maker.Shape();
}

void run(const Context& ctx, const Chamfer& c) {
  TopoDS_Shape& target = ctx.body(c.target);
  BRepFilletAPI_MakeChamfer maker(target);
  for (const auto& edge : select_edges(ctx, target, c.edges)) maker.Add(c.distance_mm, edge);
  maker.Build();
  if (!maker.IsDone()) ctx.fail("chamfer_failed", "distance too large for the selected edges");
  target = maker.Shape();
}

void run(const Context& ctx, const AddHole& h) {
  TopoDS_Shape& target = ctx.body(h.target);
  const auto* by_normal = std::get_if<FaceByNormal>(&h.face);
  if (!by_normal) ctx.fail("bad_face_selector", "add_hole needs a face_by_normal selector");
  const TopoDS_Face face = find_face(ctx, target, *by_normal);
  const auto flat = face_plane(face);
  if (!flat) ctx.fail("no_face_selected", "the selected face is not flat");
  const gp_Pnt on_plane = flat->point;
  gp_Dir normal = flat->normal;
  if (face.Orientation() == TopAbs_REVERSED) normal.Reverse();

  // position_mm are global coordinates of the two in-plane axes, in x,y,z order.
  const int n = axis_index(by_normal->axis);
  double coords[3] = {0, 0, 0};
  coords[n] = on_plane.Coord(n + 1);
  int k = 0;
  for (int i = 0; i < 3; ++i) {
    if (i != n) coords[i] = h.position_mm[k++];
  }
  const gp_Pnt centre(coords[0], coords[1], coords[2]);

  const Bnd_Box bounds = bounds_of(target);
  const BoundingBox bb = to_bbox(bounds);
  const double extent = (n == 0 ? bb.width() : n == 1 ? bb.depth() : bb.height());
  const double depth = h.depth_mm ? *h.depth_mm : extent + 2 * kThroughMargin_mm;
  // Start the drill slightly outside the face so the boolean has no coplanar cap.
  const gp_Pnt start = centre.Translated(gp_Vec(normal) * kThroughMargin_mm);
  gp_Ax2 axes(start, normal.Reversed());
  const TopoDS_Shape drill =
      BRepPrimAPI_MakeCylinder(axes, h.diameter_mm / 2.0, depth + kThroughMargin_mm).Shape();
  BRepAlgoAPI_Cut op(target, drill);
  check_boolean(ctx, op);
  target = unify(op.Shape());
}

void run(const Context& ctx, const Shell& s) {
  TopoDS_Shape& target = ctx.body(s.target);
  const BoundingBox bb = to_bbox(bounds_of(target));
  const double smallest = std::min({bb.width(), bb.depth(), bb.height()});
  if (2 * s.thickness_mm >= smallest) {
    ctx.fail("shell_failed", "wall thickness must be under half the smallest extent");
  }
  if (s.open_face) {
    // remove the opening face and thicken the rest inward: the outer surface stays put
    const auto* by_normal = std::get_if<FaceByNormal>(&*s.open_face);
    if (!by_normal) ctx.fail("bad_face_selector", "shell needs a face_by_normal open_face");
    TopTools_ListOfShape removed;
    removed.Append(find_face(ctx, target, *by_normal));
    BRepOffsetAPI_MakeThickSolid maker;
    maker.MakeThickSolidByJoin(target, removed, -s.thickness_mm, Precision::Confusion(),
                               BRepOffset_Skin, false, false, GeomAbs_Arc);
    if (!maker.IsDone()) ctx.fail("shell_failed", "the body could not be hollowed to that wall");
    target = unify(maker.Shape());
    return;
  }
  // an enclosed void: offset the whole surface inward and take it out of the body
  BRepOffsetAPI_MakeOffsetShape offset;
  offset.PerformByJoin(target, -s.thickness_mm, Precision::Confusion(), BRepOffset_Skin, false,
                       false, GeomAbs_Arc);
  if (!offset.IsDone()) ctx.fail("shell_failed", "the body could not be hollowed to that wall");
  BRepAlgoAPI_Cut op(target, offset.Shape());
  check_boolean(ctx, op);
  target = unify(op.Shape());
}

void run(const Context& ctx, const Translate& t) {
  TopoDS_Shape& target = ctx.body(t.target);
  gp_Trsf trsf;
  trsf.SetTranslation(gp_Vec(t.offset_mm[0], t.offset_mm[1], t.offset_mm[2]));
  target = BRepBuilderAPI_Transform(target, trsf, true).Shape();
}

void run(const Context& ctx, const Rotate& r) {
  TopoDS_Shape& target = ctx.body(r.target);
  gp_Trsf trsf;
  trsf.SetRotation(gp_Ax1(pnt(r.origin_mm), dir_of(r.axis)),
                   r.angle_deg * std::numbers::pi / 180.0);
  target = BRepBuilderAPI_Transform(target, trsf, true).Shape();
}

void run(const Context& ctx, const SetDimensions& s) {
  TopoDS_Shape& target = ctx.body(s.target);
  const BoundingBox bb = to_bbox(bounds_of(target));
  const double current[3] = {bb.width(), bb.depth(), bb.height()};
  const std::optional<double> wanted[3] = {s.width_mm, s.depth_mm, s.height_mm};
  double ratio[3] = {1, 1, 1};
  bool uniform = true;
  std::optional<double> common;
  for (int i = 0; i < 3; ++i) {
    if (!wanted[i]) continue;
    if (current[i] <= 0) ctx.fail("zero_extent", "body has no extent on that axis");
    ratio[i] = *wanted[i] / current[i];
    if (!common) {
      common = ratio[i];
    } else if (std::abs(*common - ratio[i]) > 1e-9) {
      uniform = false;
    }
  }
  // Scale about the bbox minimum corner so the body stays where it is.
  const gp_Pnt anchor(bb.min_x, bb.min_y, bb.min_z);
  if (uniform && common && wanted[0] && wanted[1] && wanted[2]) {
    // A uniform scale keeps planes planes and lines lines, so later selectors still match.
    gp_Trsf scale;
    scale.SetScale(anchor, *common);
    target = BRepBuilderAPI_Transform(target, scale, true).Shape();
    return;
  }
  gp_GTrsf gtrsf;
  for (int i = 0; i < 3; ++i) gtrsf.SetValue(i + 1, i + 1, ratio[i]);
  gp_Trsf to_origin, back;
  to_origin.SetTranslation(gp_Vec(anchor, gp_Pnt(0, 0, 0)));
  back.SetTranslation(gp_Vec(gp_Pnt(0, 0, 0), anchor));
  TopoDS_Shape moved = BRepBuilderAPI_Transform(target, to_origin, true).Shape();
  TopoDS_Shape scaled = BRepBuilderAPI_GTransform(moved, gtrsf, true).Shape();
  target = BRepBuilderAPI_Transform(scaled, back, true).Shape();
}

void run(const Context& ctx, const SetParameter&) {
  ctx.fail("unresolved_parameter_edit", "set_parameter must be resolved before execution");
}

}  // namespace

ExecutionResult execute(const Plan& raw_plan, double) {
  const Plan plan = resolve_parameter_edits(raw_plan);
  ExecutionResult result;
  for (const auto& op : plan.operations) {
    Context ctx{op, result.bodies};
    const bool creates = op.type == "create_box" || op.type == "create_cylinder" ||
                         op.type == "extrude";
    if (creates && result.bodies.count(op.id)) ctx.fail("duplicate_body", "body already exists");
    try {
      std::visit([&](const auto& body) { run(ctx, body); }, op.body);
    } catch (const Standard_Failure& failure) {
      ctx.fail("kernel_exception",
               failure.GetMessageString() ? failure.GetMessageString() : "unknown kernel error");
    }
    if (creates) result.order.push_back(op.id);
    result.executed.push_back(op.id);
    // Never keep an invalid body: fail loudly instead of returning corrupted geometry.
    for (const auto& [name, shape] : result.bodies) {
      if (shape.IsNull()) ctx.fail("empty_body", "body " + name + " is empty");
      if (!BRepCheck_Analyzer(shape).IsValid()) {
        ctx.fail("invalid_topology", "body " + name + " failed B-Rep validation");
      }
    }
  }
  // Consumed tools drop out of the creation order.
  std::erase_if(result.order, [&](const std::string& n) { return !result.bodies.count(n); });
  return result;
}

BodyReport report_body(const std::string& name, const TopoDS_Shape& shape) {
  BodyReport report;
  report.name = name;
  report.bbox = to_bbox(bounds_of(shape));
  GProp_GProps volume_props, surface_props;
  BRepGProp::VolumeProperties(shape, volume_props);
  BRepGProp::SurfaceProperties(shape, surface_props);
  report.volume_mm3 = volume_props.Mass();
  report.surface_area_mm2 = surface_props.Mass();
  // Explorer visits shared sub-shapes once per parent; the indexed map counts unique ones.
  auto count = [&](TopAbs_ShapeEnum kind) {
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(shape, kind, map);
    return map.Extent();
  };
  report.solids = count(TopAbs_SOLID);
  report.faces = count(TopAbs_FACE);
  report.edges = count(TopAbs_EDGE);
  report.vertices = count(TopAbs_VERTEX);
  report.valid = BRepCheck_Analyzer(shape).IsValid() && report.bbox.is_valid();
  return report;
}

void write_outputs(const ExecutionResult& result, const std::string& dir,
                   double linear_deflection_mm, double angular_deflection_rad) {
  for (const auto& [name, shape] : result.bodies) {
    const std::string base = dir + "/" + name;
    BRepTools::Write(shape, (base + ".brep").c_str());
    BRepMesh_IncrementalMesh mesher(shape, linear_deflection_mm, false, angular_deflection_rad,
                                    true);
    StlAPI_Writer writer;
    writer.ASCIIMode() = false;
    writer.Write(shape, (base + ".stl").c_str());
  }
}


namespace {

// CAD exports are routinely not solids: heal what can be healed, and report what cannot.
TopoDS_Shape heal(const TopoDS_Shape& shape) {
  ShapeFix_Shape fixer(shape);
  fixer.SetPrecision(1e-4);
  fixer.SetMaxTolerance(1e-2);
  fixer.Perform();
  return fixer.Shape();
}

// One body per top-level solid; everything else is kept together as one body, because a
// surface model is still something the user uploaded and wants to see.
void collect_bodies(const TopoDS_Shape& root, ExecutionResult& result) {
  int index = 0;
  for (TopExp_Explorer exp(root, TopAbs_SOLID); exp.More(); exp.Next()) {
    const std::string name = "body_" + std::to_string(++index);
    result.bodies[name] = heal(exp.Current());
    result.order.push_back(name);
  }
  if (!result.order.empty()) return;

  TopoDS_Compound loose;
  BRep_Builder builder;
  builder.MakeCompound(loose);
  int shells = 0;
  for (TopExp_Explorer exp(root, TopAbs_SHELL); exp.More(); exp.Next()) {
    builder.Add(loose, exp.Current());
    ++shells;
  }
  if (shells == 0) {
    for (TopExp_Explorer exp(root, TopAbs_FACE); exp.More(); exp.Next()) {
      builder.Add(loose, exp.Current());
      ++shells;
    }
  }
  if (shells > 0) {
    result.bodies["body_1"] = heal(loose);
    result.order.emplace_back("body_1");
  }
}

}  // namespace

ExecutionResult import_cad(const std::string& path, const std::string& format) {
  ExecutionResult result;
  TopoDS_Shape root;
  try {
    if (format == "step" || format == "stp") {
      STEPControl_Reader reader;
      Interface_Static::SetIVal("read.precision.mode", 1);
      Interface_Static::SetRVal("read.precision.val", 1e-4);
      if (reader.ReadFile(path.c_str()) != IFSelect_RetDone) {
        throw KernelError{"", "", "cad_unreadable", "the STEP file could not be read"};
      }
      reader.TransferRoots();
      root = reader.OneShape();
    } else if (format == "iges" || format == "igs") {
      IGESControl_Reader reader;
      if (reader.ReadFile(path.c_str()) != IFSelect_RetDone) {
        throw KernelError{"", "", "cad_unreadable", "the IGES file could not be read"};
      }
      reader.TransferRoots();
      root = reader.OneShape();
    } else {
      throw KernelError{"", "", "unsupported_format", "expected step or iges, got " + format};
    }
  } catch (const KernelError&) {
    throw;
  } catch (const Standard_Failure& failure) {
    throw KernelError{"", "", "cad_unreadable",
                      failure.GetMessageString() ? failure.GetMessageString() : "reader failed"};
  }

  if (root.IsNull()) {
    throw KernelError{"", "", "cad_empty", "the file contains no geometry"};
  }
  collect_bodies(root, result);
  if (result.order.empty()) {
    throw KernelError{"", "", "cad_empty", "the file contains no solids, shells or faces"};
  }
  result.executed.emplace_back("import");
  return result;
}

BodyReport export_cad(const std::string& brep_path, const std::string& out_path,
                      const std::string& format) {
  TopoDS_Shape shape;
  BRep_Builder builder;
  if (!BRepTools::Read(shape, brep_path.c_str(), builder) || shape.IsNull()) {
    throw KernelError{"", "", "brep_unreadable", "the B-Rep file could not be read"};
  }
  try {
    if (format == "step" || format == "stp") {
      STEPControl_Writer writer;
      Interface_Static::SetCVal("write.step.unit", "MM");
      Interface_Static::SetCVal("write.step.schema", "AP214");
      if (writer.Transfer(shape, STEPControl_AsIs) != IFSelect_RetDone) {
        throw KernelError{"", "", "export_failed", "the shape could not be translated to STEP"};
      }
      if (writer.Write(out_path.c_str()) != IFSelect_RetDone) {
        throw KernelError{"", "", "export_failed", "the STEP file could not be written"};
      }
    } else if (format == "iges" || format == "igs") {
      IGESControl_Controller::Init();
      IGESControl_Writer writer("MM", 1);  // 1 = B-Rep entities (faces, not just curves)
      if (!writer.AddShape(shape)) {
        throw KernelError{"", "", "export_failed", "the shape could not be translated to IGES"};
      }
      writer.ComputeModel();
      if (!writer.Write(out_path.c_str())) {
        throw KernelError{"", "", "export_failed", "the IGES file could not be written"};
      }
    } else {
      throw KernelError{"", "", "unsupported_format", "expected step or iges, got " + format};
    }
  } catch (const KernelError&) {
    throw;
  } catch (const Standard_Failure& failure) {
    throw KernelError{"", "", "export_failed",
                      failure.GetMessageString() ? failure.GetMessageString() : "writer failed"};
  }
  return report_body("model", shape);
}

}  // namespace physical_ai::geometry
