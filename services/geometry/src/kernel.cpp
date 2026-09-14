#include "kernel.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>

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
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepTools.hxx>
#include <Bnd_Box.hxx>
#include <GProp_GProps.hxx>
#include <GeomAbs_CurveType.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
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
    BRepAdaptor_Surface surface(face);
    if (surface.GetType() != GeomAbs_Plane) continue;
    gp_Dir normal = surface.Plane().Axis().Direction();
    if (face.Orientation() == TopAbs_REVERSED) normal.Reverse();
    if (!normal.IsEqual(wanted, kAngularTolerance)) continue;
    const gp_Pnt location = surface.Plane().Location();
    const double offset = (sel.positive ? 1.0 : -1.0) * location.Coord(idx + 1);
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
          for (TopExp_Explorer exp(shape, TopAbs_EDGE); exp.More(); exp.Next()) {
            const TopoDS_Edge edge = TopoDS::Edge(exp.Current());
            BRepAdaptor_Curve curve(edge);
            if (curve.GetType() != GeomAbs_Line) continue;
            if (curve.Line().Direction().IsParallel(axis, kAngularTolerance)) edges.push_back(edge);
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
  BRepAdaptor_Surface surface(face);
  const gp_Pnt on_plane = surface.Plane().Location();
  gp_Dir normal = surface.Plane().Axis().Direction();
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
  gp_GTrsf gtrsf;
  for (int i = 0; i < 3; ++i) {
    if (!wanted[i]) continue;
    if (current[i] <= 0) ctx.fail("zero_extent", "body has no extent on that axis");
    gtrsf.SetValue(i + 1, i + 1, *wanted[i] / current[i]);
  }
  // Scale about the bbox minimum corner so the body stays where it is.
  gp_Pnt anchor(bb.min_x, bb.min_y, bb.min_z);
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

}  // namespace physical_ai::geometry
