#include "plan.hpp"

#include <nlohmann/json.hpp>

namespace physical_ai::geometry {

using nlohmann::json;

namespace {

[[noreturn]] void fail(const std::string& message, const std::string& op_id = "") {
  throw PlanError{message, op_id};
}

double positive_mm(const json& op, const char* key, const std::string& id) {
  if (!op.contains(key) || !op[key].is_number()) fail(std::string("missing ") + key, id);
  const double value = op[key].get<double>();
  if (!(value > 0.0) || value > 10000.0) fail(std::string(key) + " out of range", id);
  return value;
}

Vec3 vec3(const json& node, const std::string& id, Vec3 fallback = {0, 0, 0}) {
  if (node.is_null()) return fallback;
  if (!node.is_array() || node.size() != 3) fail("expected a 3-vector", id);
  return {node[0].get<double>(), node[1].get<double>(), node[2].get<double>()};
}

Vec2 vec2(const json& node, const std::string& id) {
  if (!node.is_array() || node.size() != 2) fail("expected a 2-vector", id);
  return {node[0].get<double>(), node[1].get<double>()};
}

Axis axis_of(const json& node, const std::string& id, Axis fallback = Axis::Z) {
  if (node.is_null()) return fallback;
  const std::string name = node.get<std::string>();
  if (name == "x") return Axis::X;
  if (name == "y") return Axis::Y;
  if (name == "z") return Axis::Z;
  fail("unknown axis " + name, id);
}

FaceSelector face_selector(const json& node, const std::string& id) {
  const std::string kind = node.value("kind", "");
  if (kind == "face_by_normal") {
    return FaceByNormal{axis_of(node.value("axis", json()), id), node.value("sign", "+") != "-"};
  }
  if (kind == "all_faces") return AllFaces{};
  fail("unknown face selector " + kind, id);
}

EdgeSelector edge_selector(const json& node, const std::string& id) {
  const std::string kind = node.value("kind", "");
  if (kind == "all_edges") return AllEdges{};
  if (kind == "edges_parallel_to") {
    return EdgesParallelTo{axis_of(node.value("axis", json()), id), node.value("outer", false)};
  }
  if (kind == "edges_of_face") return EdgesOfFace{face_selector(node.at("face"), id)};
  fail("unknown edge selector " + kind, id);
}

Profile profile_of(const json& node, const std::string& id) {
  const std::string kind = node.value("kind", "");
  if (kind == "rectangle") {
    return RectangleProfile{positive_mm(node, "width_mm", id), positive_mm(node, "depth_mm", id)};
  }
  if (kind == "circle") return CircleProfile{positive_mm(node, "diameter_mm", id)};
  if (kind == "polygon") {
    PolygonProfile profile;
    for (const auto& point : node.at("points_mm")) profile.points_mm.push_back(vec2(point, id));
    if (profile.points_mm.size() < 3) fail("polygon needs at least 3 points", id);
    return profile;
  }
  fail("unknown profile " + kind, id);
}

std::string ref(const json& op, const char* key, const std::string& id) {
  if (!op.contains(key) || !op[key].is_string()) fail(std::string("missing ") + key, id);
  return op[key].get<std::string>();
}

OperationBody parse_body(const std::string& type, const json& op, const std::string& id) {
  if (type == "create_box") {
    return CreateBox{positive_mm(op, "width_mm", id), positive_mm(op, "depth_mm", id),
                     positive_mm(op, "height_mm", id), vec3(op.value("origin_mm", json()), id),
                     op.value("centered", false)};
  }
  if (type == "create_cylinder") {
    return CreateCylinder{positive_mm(op, "diameter_mm", id), positive_mm(op, "height_mm", id),
                          axis_of(op.value("axis", json()), id),
                          vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "create_sphere") {
    return CreateSphere{positive_mm(op, "diameter_mm", id),
                        vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "create_cone") {
    const double top = op.value("top_diameter_mm", 0.0);
    if (top < 0.0 || top > 10000.0) fail("top_diameter_mm out of range", id);
    return CreateCone{positive_mm(op, "bottom_diameter_mm", id), top,
                      positive_mm(op, "height_mm", id),
                      axis_of(op.value("axis", json()), id),
                      vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "create_torus") {
    const double outer = positive_mm(op, "outer_diameter_mm", id);
    const double tube = positive_mm(op, "tube_diameter_mm", id);
    if (2.0 * tube >= outer) fail("tube diameter must be less than half the outer diameter", id);
    return CreateTorus{outer, tube, axis_of(op.value("axis", json()), id),
                       vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "extrude") {
    return Extrude{profile_of(op.at("profile"), id), positive_mm(op, "height_mm", id),
                   vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "boolean") {
    const std::string kind = op.value("op", "");
    BooleanOp boolean_op;
    if (kind == "cut") boolean_op = BooleanOp::Cut;
    else if (kind == "fuse") boolean_op = BooleanOp::Fuse;
    else if (kind == "common") boolean_op = BooleanOp::Common;
    else fail("unknown boolean op " + kind, id);
    return Boolean{boolean_op, ref(op, "target", id), ref(op, "tool", id)};
  }
  if (type == "fillet") {
    return Fillet{ref(op, "target", id), edge_selector(op.at("edges"), id),
                  positive_mm(op, "radius_mm", id)};
  }
  if (type == "chamfer") {
    return Chamfer{ref(op, "target", id), edge_selector(op.at("edges"), id),
                   positive_mm(op, "distance_mm", id)};
  }
  if (type == "add_hole") {
    AddHole hole{ref(op, "target", id), face_selector(op.at("face"), id),
                 vec2(op.at("position_mm"), id), positive_mm(op, "diameter_mm", id), std::nullopt};
    if (op.contains("depth_mm") && !op["depth_mm"].is_null()) {
      hole.depth_mm = positive_mm(op, "depth_mm", id);
    }
    return hole;
  }
  if (type == "shell") {
    Shell shell{ref(op, "target", id), positive_mm(op, "thickness_mm", id), std::nullopt};
    if (op.contains("open_face") && !op["open_face"].is_null()) {
      shell.open_face = face_selector(op["open_face"], id);
    }
    return shell;
  }
  if (type == "translate") return Translate{ref(op, "target", id), vec3(op.at("offset_mm"), id)};
  if (type == "rotate") {
    return Rotate{ref(op, "target", id), axis_of(op.value("axis", json()), id),
                  op.at("angle_deg").get<double>(), vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "linear_pattern") {
    const int count = op.at("count").get<int>();
    if (count < 2 || count > 100) fail("pattern count must be between 2 and 100", id);
    return LinearPattern{ref(op, "target", id), axis_of(op.value("axis", json()), id), count,
                         positive_mm(op, "spacing_mm", id)};
  }
  if (type == "circular_pattern") {
    const int count = op.at("count").get<int>();
    if (count < 2 || count > 100) fail("pattern count must be between 2 and 100", id);
    const double angle = op.value("angle_deg", 360.0);
    if (!(angle > 0.0 && angle <= 360.0)) fail("pattern angle must be in (0, 360]", id);
    return CircularPattern{ref(op, "target", id), axis_of(op.value("axis", json()), id), count,
                           angle, vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "mirror") {
    return Mirror{ref(op, "target", id), axis_of(op.value("axis", json()), id),
                  op.value("offset_mm", 0.0), op.value("keep_original", true)};
  }
  if (type == "set_dimensions") {
    SetDimensions dims{ref(op, "target", id), std::nullopt, std::nullopt, std::nullopt};
    for (const char* key : {"width_mm", "depth_mm", "height_mm"}) {
      if (op.contains(key) && !op[key].is_null()) {
        const double value = positive_mm(op, key, id);
        if (std::string(key) == "width_mm") dims.width_mm = value;
        else if (std::string(key) == "depth_mm") dims.depth_mm = value;
        else dims.height_mm = value;
      }
    }
    if (!dims.width_mm && !dims.depth_mm && !dims.height_mm) fail("no dimension given", id);
    return dims;
  }
  if (type == "set_parameter") {
    return SetParameter{ref(op, "operation", id), ref(op, "parameter", id),
                        op.at("value").get<double>()};
  }
  fail("unsupported operation type " + type, id);
}

}  // namespace

Plan parse_plan(const json& document) {
  if (!document.is_object()) fail("plan must be an object");
  if (document.value("schema_version", 0) != 1) fail("unsupported plan schema_version");
  Plan plan;
  plan.goal = document.value("goal", "");
  for (const auto& node : document.value("expected_outputs", json::array())) {
    plan.expected_outputs.push_back(node.get<std::string>());
  }
  const auto& operations = document.value("operations", json::array());
  for (const auto& op : operations) {
    if (!op.is_object()) fail("operation must be an object");
    const std::string id = op.value("id", "");
    if (id.empty()) fail("operation without id");
    if (op.value("schema_version", 0) != 1) fail("unsupported operation schema_version", id);
    const std::string type = op.value("type", "");
    plan.operations.push_back(Operation{id, type, parse_body(type, op, id)});
  }
  return plan;
}

namespace {

// Numeric parameters that set_parameter may edit, per operation type.
// "origin_x_mm" -> component 0 of a vector parameter named "origin_mm"; -1 when it is not one.
int vector_component(const std::string& parameter, const std::string& stem) {
  if (parameter.size() != stem.size() + 5 || parameter.compare(0, stem.size(), stem) != 0) return -1;
  if (parameter.compare(stem.size(), 1, "_") != 0 || parameter.compare(stem.size() + 2, 3, "_mm") != 0) {
    return -1;
  }
  switch (parameter[stem.size() + 1]) {
    case 'x': return 0;
    case 'y': return 1;
    case 'z': return 2;
    default: return -1;
  }
}

bool apply_edit(Operation& target, const std::string& parameter, double value) {
  auto set = [&](double& field) {
    field = value;
    return true;
  };
  auto set_component = [&](auto& vector, const char* stem) -> bool {
    const int index = vector_component(parameter, stem);
    if (index < 0 || index >= static_cast<int>(vector.size())) return false;
    vector[static_cast<std::size_t>(index)] = value;
    return true;
  };
  return std::visit(
      [&](auto& body) -> bool {
        using T = std::decay_t<decltype(body)>;
        if constexpr (std::is_same_v<T, CreateBox>) {
          if (parameter == "width_mm") return set(body.width_mm);
          if (parameter == "depth_mm") return set(body.depth_mm);
          if (parameter == "height_mm") return set(body.height_mm);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, CreateCylinder>) {
          if (parameter == "diameter_mm") return set(body.diameter_mm);
          if (parameter == "height_mm") return set(body.height_mm);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, CreateSphere>) {
          if (parameter == "diameter_mm") return set(body.diameter_mm);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, CreateCone>) {
          if (parameter == "bottom_diameter_mm") return set(body.bottom_diameter_mm);
          if (parameter == "top_diameter_mm") return set(body.top_diameter_mm);
          if (parameter == "height_mm") return set(body.height_mm);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, CreateTorus>) {
          if (parameter == "outer_diameter_mm") return set(body.outer_diameter_mm);
          if (parameter == "tube_diameter_mm") return set(body.tube_diameter_mm);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, Extrude>) {
          if (parameter == "height_mm") return set(body.height_mm);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, Fillet>) {
          if (parameter == "radius_mm") return set(body.radius_mm);
        } else if constexpr (std::is_same_v<T, Chamfer>) {
          if (parameter == "distance_mm") return set(body.distance_mm);
        } else if constexpr (std::is_same_v<T, AddHole>) {
          if (parameter == "diameter_mm") return set(body.diameter_mm);
          if (parameter == "depth_mm") {
            body.depth_mm = value;
            return true;
          }
          return set_component(body.position_mm, "position");
        } else if constexpr (std::is_same_v<T, Shell>) {
          if (parameter == "thickness_mm") return set(body.thickness_mm);
        } else if constexpr (std::is_same_v<T, Translate>) {
          return set_component(body.offset_mm, "offset");
        } else if constexpr (std::is_same_v<T, Rotate>) {
          if (parameter == "angle_deg") return set(body.angle_deg);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, LinearPattern>) {
          if (parameter == "spacing_mm") return set(body.spacing_mm);
        } else if constexpr (std::is_same_v<T, CircularPattern>) {
          if (parameter == "angle_deg") return set(body.angle_deg);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, Mirror>) {
          if (parameter == "offset_mm") return set(body.offset_mm);
        }
        return false;
      },
      target.body);
}

// Positions may be zero or negative; sizes, radii and depths may not.
bool positional(const std::string& parameter) {
  return vector_component(parameter, "origin") >= 0 || vector_component(parameter, "position") >= 0 ||
         vector_component(parameter, "offset") >= 0 || parameter == "offset_mm";
}

}  // namespace

Plan resolve_parameter_edits(Plan plan) {
  std::vector<Operation> resolved;
  for (auto& op : plan.operations) {
    if (const auto* edit = std::get_if<SetParameter>(&op.body)) {
      bool applied = false;
      for (auto& earlier : resolved) {
        if (earlier.id == edit->operation) {
          if (!(edit->value > 0.0) && edit->parameter != "angle_deg" &&
              !positional(edit->parameter)) {
            throw PlanError{"parameter value must be positive", op.id};
          }
          applied = apply_edit(earlier, edit->parameter, edit->value);
          break;
        }
      }
      if (!applied) throw PlanError{"cannot edit " + edit->parameter + " of " + edit->operation, op.id};
      continue;
    }
    resolved.push_back(std::move(op));
  }
  plan.operations = std::move(resolved);
  return plan;
}

const char* axis_name(Axis axis) noexcept {
  switch (axis) {
    case Axis::X: return "x";
    case Axis::Y: return "y";
    case Axis::Z: return "z";
  }
  return "?";
}

}  // namespace physical_ai::geometry
